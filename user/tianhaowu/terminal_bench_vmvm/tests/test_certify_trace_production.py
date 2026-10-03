from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import certify_trace_production as production
import pytest
from deployment_endpoint import load_deployment_endpoint
from deployment_proxy_policy import load_deployment_proxy_policy
from guard_success_receipt import (
    build_guard_success_receipt,
    write_guard_success_receipt,
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


def _json_digest(value: dict[str, Any]) -> str:
    return _sha256_bytes(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    )


def _trace(trace_id: str, task: str, *, start: float, end: float) -> dict[str, Any]:
    request = {
        "model": "Kimi-K3",
        "reasoning_effort": "max",
        "chat_template_kwargs": {
            "enable_thinking": True,
            "preserve_thinking": True,
        },
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
        "is_completed": True,
        "stop_condition": "task_completed",
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
                    "request": {
                        "kind": "full",
                        "sha256": _json_digest(request),
                        "body": request,
                    },
                    "response": {
                        "kind": "exact_provider_json",
                        "sha256": _json_digest(response),
                        "body": response,
                    },
                },
            },
        ],
    }


def _use_normalized_stream_responses(results: Path) -> None:
    rows = [json.loads(line) for line in results.read_text().splitlines()]
    for row in rows:
        for node in row["nodes"]:
            if node.get("sampled") is not True:
                continue
            exact = node["model_io"]["response"]["body"]
            choice = exact["choices"][0]
            normalized = {
                "id": exact["id"],
                "created": exact["created"],
                "model": exact["model"],
                "message": {
                    "role": "assistant",
                    "content": choice["message"].get("content"),
                    "reasoning_content": choice["message"].get("reasoning_content"),
                },
                "finish_reason": choice["finish_reason"],
                "usage": node["usage"],
            }
            node["model_io"]["response"] = {
                "kind": "normalized_stream_response",
                "sha256": _json_digest(normalized),
                "body": normalized,
            }
    results.write_text("".join(f"{json.dumps(row)}\n" for row in rows))


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setattr(production, "EXPECTED_TASKS", 2)
    monkeypatch.setattr(production, "EXPECTED_MOBIUS_STEADY_STATE_CONCURRENCY", 2)
    monkeypatch.setattr(production, "EXPECTED_MOBIUS_LEASE_START_CONCURRENCY", 2)

    run_dir = tmp_path / "run"
    inputs_dir = run_dir / "inputs"
    inputs_dir.mkdir(parents=True)
    run_dir.chmod(0o700)
    writer_lock = run_dir / ".writer.lock"
    writer_lock.touch(mode=0o600)
    writer_lock.chmod(0o600)

    task_file = tmp_path / "approved.tasks.txt"
    task_file.write_text("opaque-a\nopaque-b\n")
    production_config = tmp_path / "production.toml"
    production_config.write_text('model = "Kimi-K3"\n')
    resolved_config = run_dir / "config.toml"
    resolved_config.write_bytes(production_config.read_bytes())
    inputs_manifest = inputs_dir / "manifest.json"
    inputs_manifest.write_text('{"config":{},"task_file":{}}\n')
    image_manifest = inputs_dir / "image_manifest.json"
    image_manifest.write_text('{"images":{}}\n')
    launch_certificate = tmp_path / "launch.json"
    launch_certificate.write_text('{"state":"passed"}\n')
    oracle_receipt = tmp_path / "oracle.json"
    oracle_receipt.write_text('{"state":"passed"}\n')
    capacity_checkpoint = tmp_path / "capacity.json"
    capacity_checkpoint.write_text('{"state":"passed"}\n')

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
                "extras": {
                    "proxy_type": "litellm",
                    "sticky": True,
                    "redis_port": 6379,
                },
            }
        )
        + "\n"
    )
    spec_sha256 = _sha256_bytes(spec.read_bytes())
    endpoint = load_deployment_endpoint(
        proxy_info,
        deployment_id=deployment_id,
        expected_model="Kimi-K3",
        deployment_spec=spec,
        expected_proxy_info_sha256=_sha256_bytes(proxy_info.read_bytes()),
    ).binding
    backend = f"backend-sha256:{hashlib.sha256(b'http://worker-0:8000/v1').hexdigest()}"
    route_generation = {
        "schema_version": 2,
        "coordinator": {
            "slurm_job_id": "900",
            "started_at": "2026-09-19T00:00:00Z",
        },
        "proxy": {
            "slurm_job_id": "12345",
            "first_ready_at": "2026-09-19T00:30:00Z",
        },
        "routes": [
            {
                "slurm_job_id": "12345",
                "started_at": "2026-09-19T01:00:00Z",
                "backend_sha256": backend,
            }
        ],
    }
    proxy_policy = load_deployment_proxy_policy(
        spec,
        expected_spec_sha256=spec_sha256,
        expected_request_timeout=43_200,
    )
    readiness = tmp_path / "readiness.json"
    readiness.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "state": "passed",
                "deployment": deployment_id,
                "observed_spec_sha256": spec_sha256,
                "expected_routes": 1,
                "endpoint": endpoint,
                "proxy_policy": proxy_policy,
                "serving_route_generation": route_generation,
                "last_status": {
                    "schema_version": 4,
                    "deployment_id": deployment_id,
                    "phase": "serving",
                    "desired": 1,
                    "ready": 1,
                    "running_not_ready": 0,
                    "pending": 0,
                    "coordinator_incarnation": route_generation["coordinator"],
                    "coord_ticks_completed": 10,
                    "serving_route_generation": route_generation,
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
            },
            sort_keys=True,
        )
        + "\n"
    )

    results = run_dir / "results.jsonl"
    results.write_text(
        "\n".join(
            json.dumps(trace)
            for trace in (
                _trace("trace-a", "opaque-a", start=1.0, end=3.0),
                _trace("trace-b", "opaque-b", start=2.0, end=4.0),
            )
        )
        + "\n"
    )
    identity = {
        "schema_version": 1,
        "role": "mobius",
        "source": {
            "project_root": str(production.PROJECT_ROOT),
            "prime_rl_commit": "1" * 40,
            "prime_rl_tree_sha256": "2" * 64,
            "verifiers_commit": "3" * 40,
            "verifiers_tree_sha256": "4" * 64,
            "renderers_commit": "5" * 40,
            "renderers_tree_sha256": "6" * 64,
            "vmvm_tb_v2_sha256": "7" * 64,
        },
        "config": {
            "source": _record(production_config),
            "resolved": _record(resolved_config),
        },
        "inputs": {
            "manifest": _record(inputs_manifest),
            "task_file": _record(task_file, count=2),
            "image_manifest": _record(image_manifest),
        },
        "dataset": {
            "kind": "git_revision",
            "path": str(tmp_path / "dataset"),
            "revision": "8" * 40,
        },
        "deployment": {
            "id": deployment_id,
            "endpoint": endpoint,
            "serving_route_generation": route_generation,
            "proxy_policy": proxy_policy,
            "spec": _record(spec),
            "readiness_checkpoint": _record(readiness),
            "smoke_checkpoint": _record(capacity_checkpoint),
            "promotion_certificate": _record(launch_certificate),
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
            "runtime": {"type": "vmvm"},
            "vmvm_environment": {"lease_start_concurrency": 2},
        },
    }
    identity_sha256 = _json_digest(identity)
    envelope = {
        "schema_version": 1,
        "eval_run_identity_sha256": identity_sha256,
        "identity": identity,
    }
    identity_path = run_dir / "eval_run_identity.json"
    identity_path.write_text(json.dumps(envelope, sort_keys=True) + "\n")
    invocation_path = run_dir / "eval_invocations.jsonl"
    invocation_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "eval_run_identity_sha256": identity_sha256,
                "role": "mobius",
                "resume": False,
                "host": "test-host",
                "slurm_job_id": "101",
            },
            sort_keys=True,
        )
        + "\n"
    )
    (run_dir / "provenance.txt").write_text("host=test-host\nslurm_job_id=101\n")

    telemetry = ConcurrencyTelemetry(
        run_dir / "concurrency_telemetry.json",
        eval_run_identity_sha256=identity_sha256,
        eval_run_role="mobius",
        slurm_job_id="101",
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
    guard_receipt = build_guard_success_receipt(
        eval_run_identity_sha256=identity_sha256,
        eval_run_role="mobius",
        eval_run_identity=identity_path,
        eval_invocations=invocation_path,
        results=results,
        deployment_id=deployment_id,
        deployment_spec_sha256=spec_sha256,
        readiness_checkpoint=readiness,
        readiness_checkpoint_sha256=_sha256_bytes(readiness.read_bytes()),
        endpoint=endpoint,
        serving_route_generation=route_generation,
        proxy_policy=proxy_policy,
        concurrency_telemetry=telemetry.path,
    )
    write_guard_success_receipt(run_dir / "route_guard_success.json", guard_receipt)

    task_record = _record(task_file)
    config_record = _record(production_config)
    oracle_record = _record(oracle_receipt)
    image_record = _record(image_manifest)

    def launch_validator(*_args: object, **_kwargs: object) -> dict[str, Any]:
        return {
            "launch_certificate_sha256": "9" * 64,
            "gates": {
                "oracle_promotion": {
                    "artifact": oracle_record,
                    "dataset_revision": identity["dataset"]["revision"],
                    "image_manifest_sha256": image_record["sha256"],
                }
            },
            "production": {
                "approved_manifest": {**task_record, "count": 2},
                "config": config_record,
                "contract": {
                    **identity["contract"],
                    "num_tasks": 2,
                    "execution": {
                        "http_max_connections": 2,
                        "http_max_keepalive_connections": 2,
                        "multiplex": 2,
                        "rollout_concurrency": 2,
                    },
                    "timeouts": dict(production.EXPECTED_FULL_TIMEOUTS),
                    "vmvm": True,
                },
            },
        }

    runtime_python = Path("/usr/bin/python3.12")
    stdlib = tmp_path / "stdlib"
    site_packages = tmp_path / "site-packages"
    stdlib.mkdir()
    site_packages.mkdir()
    source_attestation = {
        "project_root": str(production.PROJECT_ROOT),
        "prime_rl_commit": identity["source"]["prime_rl_commit"],
        "prime_rl_git_tree": "a" * 40,
        "gitlinks": {
            "pydantic_config": "b" * 40,
            "renderers": identity["source"]["renderers_commit"],
            "verifiers": identity["source"]["verifiers_commit"],
        },
        "import_manifests": {
            "prime_rl": "c" * 64,
            "pydantic_config": "d" * 64,
            "renderers": "e" * 64,
            "verifiers": "f" * 64,
        },
        "artifacts": production._require_auditor_source(identity),
        "runtime": {
            "isolation": {
                "dont_write_bytecode": True,
                "isolated": True,
                "no_site": True,
                "pycache_prefix": "fresh_empty_mode_0500",
                "safe_path": True,
            },
            "submission": {
                "environment": "env_i_exact_allowlist",
                "sbatch_export": "NONE",
            },
            "python": _record(runtime_python),
            "stdlib": {"path": str(stdlib), "tree_sha256": "1" * 64},
            "site_packages": {"path": str(site_packages), "tree_sha256": "2" * 64},
            "tools": {label: _record(Path(path)) for label, path in production.RUNTIME_TOOL_PATHS.items()},
        },
    }
    assert set(source_attestation["artifacts"]) == production.EXPECTED_SOURCE_ARTIFACT_LABELS
    authorization_body = {
        "schema_version": 1,
        "artifact_type": production.AUTHORIZATION_ARTIFACT_TYPE,
        "state": "approved",
        "authorization_nonce": "0123456789abcdef" * 4,
        "audit_submission": {
            "cluster": "test-cluster",
            "job_name": "trace-production-audit-0123456789abcdef",
            "launch_token_sha256": _sha256_bytes(("0123456789abcdef" * 4).encode()),
            "log_path": str(tmp_path / "audit_%j.log"),
            "reservation_dir": str(tmp_path / "audit-reservation"),
            "policy": {
                "held_submission": True,
                "one_shot": True,
                "requeue": False,
                "wrapper_transport": "sbatch_stdin_exact_bytes",
            },
            "resources": {
                "account": "ram",
                "cpus_per_task": 2,
                "memory": "8G",
                "nodes": 1,
                "ntasks": 1,
                "partition": "cpu_x86",
                "qos": "cpu_x86_lowest",
                "time_limit": "02:00:00",
            },
        },
        "audit_policy": production._expected_audit_policy(),
        "run": {
            "path": str(run_dir.resolve()),
            "role": "mobius",
            "resume": False,
            "eval_run_identity_file_sha256": _sha256_bytes(identity_path.read_bytes()),
            "eval_run_identity_sha256": identity_sha256,
        },
        "inputs": {
            "task_file": {**task_record, "count": 2},
            "production_config": config_record,
            "launch_certificate": _record(launch_certificate),
            "oracle_receipt": oracle_record,
        },
        "source": source_attestation,
        "scheduler": _terminal("101", "test-cluster"),
    }
    authorization = {
        **authorization_body,
        "authorization_sha256": _sha256_bytes(production._canonical_json(authorization_body)),
    }
    authorization_path = tmp_path / "audit_authorization.json"
    authorization_path.write_bytes(production._canonical_json(authorization) + b"\n")
    authorization_path.chmod(0o400)
    reservation = tmp_path / "audit-reservation"
    reservation.mkdir(mode=0o700)
    submission_records: dict[str, dict[str, object]] = {}
    for label, name in (
        ("intent", "launch_intent.json"),
        ("held_authorization", "held_authorization.json"),
        ("submission_receipt", "submission_receipt.json"),
        ("activation_permit", "activation_permit.json"),
    ):
        path = reservation / name
        path.write_text(f'{{"kind":"{label}"}}\n')
        path.chmod(0o400)
        submission_records[label] = _record(path)
    reservation.chmod(0o500)
    reservation_status = reservation.stat(follow_symlinks=False)
    reservation_parent_status = reservation.parent.stat(follow_symlinks=False)
    submission_attestation = {
        "reservation": {
            "identity": {
                "device": reservation_status.st_dev,
                "inode": reservation_status.st_ino,
                "owner_uid": os.getuid(),
                "parent_device": reservation_parent_status.st_dev,
                "parent_inode": reservation_parent_status.st_ino,
            },
            "path": str(reservation),
            "mode": "0500",
        },
        **submission_records,
        "job": {
            "cluster": "test-cluster",
            "id": "202",
            "name": "trace-production-audit-0123456789abcdef",
        },
    }
    kwargs = {
        "audit_authorization": authorization_path,
        "audit_authorization_sha256": _sha256_bytes(authorization_path.read_bytes()),
        "slurm_cluster": "test-cluster",
        "expected_task_file": task_file,
        "expected_task_file_sha256": task_record["sha256"],
        "expected_production_config": production_config,
        "expected_production_config_sha256": config_record["sha256"],
        "expected_launch_certificate": launch_certificate,
        "expected_launch_certificate_sha256": _sha256_bytes(launch_certificate.read_bytes()),
        "expected_oracle_receipt": oracle_receipt,
        "expected_oracle_receipt_sha256": oracle_record["sha256"],
        "expected_traces": 2,
        "identity_loader": lambda *_args, **_kwargs: envelope,
        "launch_validator": launch_validator,
        "runtime_revalidator": lambda: source_attestation,
        "submission_attestation": submission_attestation,
        "submission_revalidator": lambda: submission_attestation,
    }
    return {
        "authorization": authorization_path,
        "run_dir": run_dir,
        "results": results,
        "source_attestation": source_attestation,
        "task_file": task_file,
        "writer_lock": writer_lock,
        "kwargs": kwargs,
    }


def _terminal(job_id: str, cluster: str) -> dict[str, Any]:
    allocation = {
        "JobIDRaw": job_id,
        "JobName": "production-trace",
        "User": "tianhaowu",
        "UID": str(production.os.getuid()),
        "Account": "ram",
        "Partition": "cpu_x86",
        "QOS": "cpu_x86_lowest",
        "State": "COMPLETED",
        "ExitCode": "0:0",
        "DerivedExitCode": "0:0",
        "Submit": "2026-09-19T00:00:00",
        "Start": "2026-09-19T00:01:00",
        "End": "2026-09-19T00:02:00",
        "Elapsed": "00:01:00",
        "Restarts": "0",
        "NNodes": "1",
        "AllocCPUS": "2",
        "ReqMem": "8Gn",
    }
    step = {
        **allocation,
        "JobIDRaw": f"{job_id}.batch",
        "JobName": "batch",
        # Slurm leaves these allocation-only accounting fields empty for
        # completed step rows on the production cluster.
        "DerivedExitCode": "",
        "Restarts": "",
    }
    scontrol = {
        "Account": "ram",
        "Command": "/immutable/run_oracle.sbatch",
        "JobId": job_id,
        "JobName": "production-trace",
        "JobState": "COMPLETED",
        "Partition": "cpu_x86",
        "QOS": "cpu_x86_lowest",
        "Requeue": "0",
        "Restarts": "0",
        "UserId": f"tianhaowu({production.os.getuid()})",
        "WorkDir": "/immutable/source",
    }
    return {
        "cluster": cluster,
        "job_id": job_id,
        "allocation": allocation,
        "steps": [step],
        "sacct_fields": list(production.SACCT_FIELDS),
        "sacct_sha256": "a" * 64,
        "scontrol": scontrol,
        "scontrol_sha256": "b" * 64,
        "queue": {
            "allocation_rows": 0,
            "allocation_sha256": _sha256_bytes(b""),
            "step_rows": 0,
            "steps_sha256": _sha256_bytes(b""),
        },
        "requeue": {
            "duplicate_allocation_rows": 0,
            "restarts": 0,
            "scontrol_requeue": 0,
        },
        "terminal_observations": 2,
    }


def test_terminal_query_uses_only_explicit_cluster_and_readable_auth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    certificate = tmp_path / "client.crt"
    key = tmp_path / "client.key"
    certificate.write_text("synthetic certificate\n")
    key.write_text("synthetic key\n")
    monkeypatch.setenv("THRIFT_TLS_CL_CERT_PATH", str(certificate))
    monkeypatch.setenv("THRIFT_TLS_CL_KEY_PATH", str(key))
    expected = _terminal("101", "test-cluster")
    sacct_raw = (
        "\n".join(
            "|".join(row[field] for field in production.SACCT_FIELDS)
            for row in [expected["allocation"], *expected["steps"]]
        )
        + "\n"
    ).encode()
    scontrol_raw = (" ".join(f"{key}={value}" for key, value in expected["scontrol"].items()) + "\n").encode()
    observed: list[tuple[object, object]] = []

    def run(command, **kwargs):
        observed.append((command, kwargs))
        if command[0] == "/usr/bin/squeue":
            raw = b""
        elif command[0] == "/usr/bin/sacct":
            raw = sacct_raw
        else:
            raw = scontrol_raw
        return SimpleNamespace(returncode=0, stdout=raw, stderr=b"")

    monkeypatch.setattr(production.subprocess, "run", run)
    result = production.require_slurm_terminal(
        "101",
        "test-cluster",
        sleeper=lambda _seconds: None,
    )
    expected["sacct_sha256"] = _sha256_bytes(sacct_raw)
    expected["scontrol_sha256"] = _sha256_bytes(scontrol_raw)
    assert result == expected
    assert observed[0][0] == [
        "/usr/bin/squeue",
        "-M",
        "test-cluster",
        "--noheader",
        "--jobs",
        "101",
        "--format=%A|%j|%u|%T",
    ]
    assert observed[1][0] == [
        "/usr/bin/squeue",
        "-M",
        "test-cluster",
        "--steps",
        "--noheader",
        "--jobs",
        "101",
        "--format=%i|%j|%u|%T",
    ]
    assert observed[0][1]["env"] == {
        "HOME": "/nonexistent",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
        "THRIFT_TLS_CL_CERT_PATH": str(certificate),
        "THRIFT_TLS_CL_KEY_PATH": str(key),
    }

    duplicate = sacct_raw.replace(b"\n", b"\n" + sacct_raw.splitlines()[0] + b"\n", 1)

    def duplicate_run(command, **_kwargs):
        if command[0] == "/usr/bin/squeue":
            raw = b""
        elif command[0] == "/usr/bin/sacct":
            raw = duplicate
        else:
            raw = scontrol_raw
        return SimpleNamespace(returncode=0, stdout=raw, stderr=b"")

    monkeypatch.setattr(production.subprocess, "run", duplicate_run)
    with pytest.raises(
        production.ProductionCertificateError,
        match="evaluation_job_identity_invalid",
    ):
        production.require_slurm_terminal("101", "test-cluster", sleeper=lambda _seconds: None)

    monkeypatch.delenv("THRIFT_TLS_CL_KEY_PATH")
    with pytest.raises(production.ProductionCertificateError, match="scheduler_auth_invalid"):
        production.require_slurm_terminal("101", "test-cluster", sleeper=lambda _seconds: None)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("State", "FAILED"),
        ("ExitCode", "1:0"),
        ("DerivedExitCode", "1:0"),
        ("Restarts", "1"),
    ],
)
def test_terminal_record_rejects_nonzero_or_restarted_steps(
    field: str,
    value: str,
) -> None:
    record = _terminal("101", "test-cluster")
    record["steps"][0][field] = value
    with pytest.raises(
        production.ProductionCertificateError,
        match="^evaluation_job_not_successfully_terminal$",
    ):
        production._validate_terminal_record(
            record,
            expected_job_id="101",
            expected_cluster="test-cluster",
            authorized_record=record,
        )


def test_terminal_query_rejects_any_live_allocation_or_step(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    certificate = tmp_path / "client.crt"
    key = tmp_path / "client.key"
    certificate.write_text("synthetic certificate\n")
    key.write_text("synthetic key\n")
    monkeypatch.setenv("THRIFT_TLS_CL_CERT_PATH", str(certificate))
    monkeypatch.setenv("THRIFT_TLS_CL_KEY_PATH", str(key))
    monkeypatch.setattr(
        production.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=b"101|production-trace|tianhaowu|RUNNING\n",
            stderr=b"",
        ),
    )
    with pytest.raises(production.ProductionCertificateError, match="evaluation_job_still_queued"):
        production.require_slurm_terminal("101", "test-cluster", sleeper=lambda _seconds: None)


def test_final_terminal_query_is_publication_adjacent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    events: list[str] = []
    original_publish = production._publish_certificate

    def terminal(job_id: str, cluster: str) -> dict[str, Any]:
        events.append("terminal")
        return _terminal(job_id, cluster)

    def runtime() -> dict[str, Any]:
        events.append("runtime")
        return fixture["source_attestation"]

    def submission() -> dict[str, Any]:
        events.append("submission")
        return fixture["kwargs"]["submission_attestation"]

    def publish(*args: object, **kwargs: object) -> dict[str, Any]:
        events.append("publish")
        return original_publish(*args, **kwargs)

    monkeypatch.setattr(production, "_publish_certificate", publish)
    fixture["kwargs"]["runtime_revalidator"] = runtime
    fixture["kwargs"]["submission_revalidator"] = submission
    production.certify_production(
        fixture["run_dir"],
        terminal_validator=terminal,
        **fixture["kwargs"],
    )
    assert events[-4:] == ["runtime", "submission", "terminal", "publish"]


def test_certifies_terminal_nonresume_production_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    certificate = production.certify_production(
        fixture["run_dir"],
        terminal_validator=_terminal,
        **fixture["kwargs"],
    )

    checkpoint = fixture["run_dir"] / production.CHECKPOINT_NAME
    assert certificate["state"] == "audited"
    assert certificate["authoritative"] is False
    assert certificate["evaluation_job"] == _terminal("101", "test-cluster")
    assert certificate["audit_policy"] == {
        "expected_traces": 2,
        "rollouts_per_task": 1,
        "require_reasoning": True,
        "require_model_io": True,
        "model_io_contract": production.EXPECTED_MODEL_IO_CONTRACT,
        "require_request_graph_match": True,
        "require_exact_provider_json": True,
        "require_token_data": False,
        "require_logprobs": False,
        "require_clean_stop": True,
        "max_sequence_tokens": 262_144,
        "aggregate_only": True,
    }
    assert certificate["qualified_rollout_contract"] == {
        "capture_model_io": True,
        "context_tokens": {
            "max_input_tokens": 262_144,
            "max_output_tokens": 262_144,
            "max_total_tokens": 262_144,
        },
        "execution": {
            "http_max_connections": 2,
            "http_max_keepalive_connections": 2,
            "lease_start_concurrency": 2,
            "multiplex": 2,
            "rollout_concurrency": 2,
        },
        "model": "Kimi-K3",
        "num_rollouts": 1,
        "num_tasks": 2,
        "pass_at_1": True,
        "reasoning_effort": "max",
        "retain_traces": False,
        "runtime_provider": "vmvm",
        "sampling_max_tokens": 32_768,
        "thinking": {"enable_thinking": True, "preserve_thinking": True},
        "timeouts": production.EXPECTED_FULL_TIMEOUTS,
        "vmvm_source_sha256": "7" * 64,
    }
    assert len(certificate["artifacts"]) >= 20
    wrapper = Path(production.__file__).with_name("run_trace_production_audit.sbatch")
    assert certificate["artifacts"]["source_production_audit_wrapper"] == _record(wrapper)
    submitter = Path(production.__file__).with_name("submit_trace_production_audit.sh")
    assert certificate["artifacts"]["source_production_audit_submitter"] == _record(submitter)
    workflow = Path(production.__file__).parent
    assert certificate["artifacts"]["source_strict_sft_exporter"] == _record(workflow / "export_sft.py")
    assert certificate["artifacts"]["source_sft_preflight_cli"] == _record(workflow / "preflight_sft.py")
    assert certificate["artifacts"]["source_sft_target_rendering_contract"] == _record(
        workflow / "configs/sft/target-rendering-contract.json"
    )
    assert certificate["artifacts"]["source_sft_export_preflight"] == _record(
        production.PROJECT_ROOT / "src/prime_rl/trainer/sft/export_preflight.py"
    )
    assert certificate["artifacts"]["source_sft_training_entrypoint"] == _record(
        production.PROJECT_ROOT / "src/prime_rl/trainer/sft/train.py"
    )
    assert certificate["artifacts"]["source_vmvm_backend"] == _record(
        production.PROJECT_ROOT / "environments/vmvm_tb_v2/vmvm_tb_v2/_vacli/backend.py"
    )
    assert certificate["artifacts"]["source_terminal_bench_taskset"] == _record(
        workflow / "terminal_bench_vmvm/taskset.py"
    )
    assert certificate["sft_training_readiness"] == {
        "established": False,
        "trace_certificate_sufficient": False,
        "required_downstream_artifacts": [
            "format_v3_export_manifest",
            "schema_v2_immutable_local_tokenizer_tree_preflight_attestation",
        ],
    }
    serialized_certificate = production._canonical_json(certificate)
    for private_value in (
        b"opaque-a",
        b"synthetic",
        b"retained reasoning",
        b'"tool_calls"',
        b'"messages"',
    ):
        assert private_value not in serialized_certificate
    assert checkpoint.is_file()
    assert stat.S_IMODE(checkpoint.stat().st_mode) == 0o444
    payload = fixture["run_dir"] / production.PAYLOAD_NAME
    assert payload.is_file() and stat.S_IMODE(payload.stat().st_mode) == 0o444
    assert json.loads(payload.read_bytes()) == certificate
    marker = json.loads(checkpoint.read_bytes())
    assert marker["state"] == "passed"
    assert marker["certificate"] == {
        "path": str(payload),
        "sha256": _sha256_bytes(payload.read_bytes()),
    }


def test_rejects_nonterminal_job_without_publishing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)

    def failed_terminal(job_id: str, cluster: str) -> dict[str, Any]:
        record = _terminal(job_id, cluster)
        record["allocation"]["State"] = "FAILED"
        return record

    with pytest.raises(
        production.ProductionCertificateError,
        match="evaluation_job_authorization_mismatch",
    ):
        production.certify_production(
            fixture["run_dir"],
            terminal_validator=failed_terminal,
            **fixture["kwargs"],
        )
    assert not (fixture["run_dir"] / production.CHECKPOINT_NAME).exists()


def test_rejects_normalized_stream_response_without_publishing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    _use_normalized_stream_responses(fixture["results"])

    with pytest.raises(production.ProductionCertificateError, match="trace_audit_failed"):
        production.certify_production(
            fixture["run_dir"],
            terminal_validator=_terminal,
            **fixture["kwargs"],
        )
    assert not (fixture["run_dir"] / production.CHECKPOINT_NAME).exists()


def test_rejects_unclean_stop_condition_without_publishing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    rows = [json.loads(line) for line in fixture["results"].read_text().splitlines()]
    rows[0]["stop_condition"] = "HarnessTimeout"
    fixture["results"].write_text("".join(f"{json.dumps(row)}\n" for row in rows))

    with pytest.raises(production.ProductionCertificateError, match="trace_audit_failed"):
        production.certify_production(
            fixture["run_dir"],
            terminal_validator=_terminal,
            **fixture["kwargs"],
        )
    assert not (fixture["run_dir"] / production.CHECKPOINT_NAME).exists()
    assert not (fixture["run_dir"] / production.PAYLOAD_NAME).exists()


def test_authorization_and_runtime_attestation_are_revalidated_before_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    changed = dict(fixture["source_attestation"])
    changed["prime_rl_git_tree"] = "9" * 40
    fixture["kwargs"]["runtime_revalidator"] = lambda: changed
    with pytest.raises(production.ProductionCertificateError, match="verified_runtime_changed"):
        production.certify_production(
            fixture["run_dir"],
            terminal_validator=_terminal,
            **fixture["kwargs"],
        )
    assert not (fixture["run_dir"] / production.CHECKPOINT_NAME).exists()
    assert not (fixture["run_dir"] / production.PAYLOAD_NAME).exists()

    second = _fixture(tmp_path / "second", monkeypatch)
    authorization = second["authorization"]
    authorization.chmod(0o600)
    authorization.write_bytes(authorization.read_bytes() + b" ")
    authorization.chmod(0o400)
    with pytest.raises(production.ProductionCertificateError, match="audit_authorization_changed"):
        production.certify_production(
            second["run_dir"],
            terminal_validator=_terminal,
            **second["kwargs"],
        )
    assert not (second["run_dir"] / production.CHECKPOINT_NAME).exists()


def test_task_mutation_and_step_identity_mismatch_never_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)

    def mutate_task(job_id: str, cluster: str) -> dict[str, Any]:
        fixture["task_file"].write_text("opaque-a\nopaque-b\nopaque-c\n")
        return _terminal(job_id, cluster)

    with pytest.raises(
        production.ProductionCertificateError,
        match="expected_task_file_changed|artifact_hash_mismatch",
    ):
        production.certify_production(
            fixture["run_dir"],
            terminal_validator=mutate_task,
            **fixture["kwargs"],
        )
    assert not (fixture["run_dir"] / production.CHECKPOINT_NAME).exists()

    second = _fixture(tmp_path / "second", monkeypatch)

    def mutate_step(job_id: str, cluster: str) -> dict[str, Any]:
        record = _terminal(job_id, cluster)
        record["steps"][0]["Restarts"] = "1"
        return record

    with pytest.raises(
        production.ProductionCertificateError,
        match="evaluation_job_authorization_mismatch",
    ):
        production.certify_production(
            second["run_dir"],
            terminal_validator=mutate_step,
            **second["kwargs"],
        )
    assert not (second["run_dir"] / production.CHECKPOINT_NAME).exists()


def test_terminal_gate_mutation_is_caught_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)

    def mutating_terminal(job_id: str, cluster: str) -> dict[str, str]:
        with fixture["results"].open("ab") as handle:
            handle.write(b" ")
        return _terminal(job_id, cluster)

    with pytest.raises(
        production.ProductionCertificateError,
        match="artifact_hash_mismatch:results",
    ):
        production.certify_production(
            fixture["run_dir"],
            terminal_validator=mutating_terminal,
            **fixture["kwargs"],
        )
    assert not (fixture["run_dir"] / production.CHECKPOINT_NAME).exists()


def test_second_terminal_gate_mutation_is_caught_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    calls = 0

    def mutating_second_terminal(job_id: str, cluster: str) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 2:
            with fixture["results"].open("ab") as handle:
                handle.write(b" ")
        return _terminal(job_id, cluster)

    with pytest.raises(
        production.ProductionCertificateError,
        match="results_changed_during_audit",
    ):
        production.certify_production(
            fixture["run_dir"],
            terminal_validator=mutating_second_terminal,
            **fixture["kwargs"],
        )
    assert calls == 2
    assert not (fixture["run_dir"] / production.CHECKPOINT_NAME).exists()


def test_terminal_gate_writer_lock_replacement_is_caught_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)

    def replacing_terminal(job_id: str, cluster: str) -> dict[str, str]:
        fixture["writer_lock"].unlink()
        fixture["writer_lock"].touch(mode=0o600)
        fixture["writer_lock"].chmod(0o600)
        return _terminal(job_id, cluster)

    with pytest.raises(production.ProductionCertificateError, match="writer_lock_changed"):
        production.certify_production(
            fixture["run_dir"],
            terminal_validator=replacing_terminal,
            **fixture["kwargs"],
        )
    assert not (fixture["run_dir"] / production.CHECKPOINT_NAME).exists()


def test_rejects_provenance_job_mismatch_and_active_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    (fixture["run_dir"] / "provenance.txt").write_text("host=test-host\nslurm_job_id=202\n")
    with pytest.raises(
        production.ProductionCertificateError,
        match="terminal_guard_invalid",
    ):
        production.certify_production(
            fixture["run_dir"],
            terminal_validator=_terminal,
            **fixture["kwargs"],
        )
    assert not (fixture["run_dir"] / production.CHECKPOINT_NAME).exists()

    second = _fixture(tmp_path / "second", monkeypatch)
    with second["writer_lock"].open("rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(production.ProductionCertificateError, match="writer_active"):
            production.certify_production(
                second["run_dir"],
                terminal_validator=_terminal,
                **second["kwargs"],
            )
    assert not (second["run_dir"] / production.CHECKPOINT_NAME).exists()


def test_rejects_wrong_writer_lock_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    fixture["writer_lock"].chmod(0o644)
    with pytest.raises(production.ProductionCertificateError, match="writer_lock_invalid"):
        production.certify_production(
            fixture["run_dir"],
            terminal_validator=_terminal,
            **fixture["kwargs"],
        )
    assert not (fixture["run_dir"] / production.CHECKPOINT_NAME).exists()


@pytest.mark.parametrize("mutation", ("mode", "symlink", "hardlink"))
def test_stable_artifact_open_rejects_aliases_and_unsafe_identity(
    tmp_path: Path,
    mutation: str,
) -> None:
    source = tmp_path / "artifact.json"
    source.write_text('{"ok":true}\n')
    candidate = source
    if mutation == "mode":
        source.chmod(0o666)
    elif mutation == "symlink":
        candidate = tmp_path / "alias.json"
        candidate.symlink_to(source)
    else:
        os.link(source, tmp_path / "second.json")
    with pytest.raises(production.ProductionCertificateError):
        production._open_stable_file(candidate, label="test_artifact")


def test_stable_artifact_detects_path_replacement_after_open(tmp_path: Path) -> None:
    source = tmp_path / "artifact.json"
    source.write_text('{"ok":true}\n')
    snapshot = production._open_stable_file(source, label="test_artifact")
    displaced = tmp_path / "displaced.json"
    source.rename(displaced)
    source.write_text('{"ok":true}\n')
    try:
        with pytest.raises(
            production.ProductionCertificateError,
            match="^artifact_changed$",
        ):
            snapshot.read()
    finally:
        snapshot.close()


def test_results_snapshot_is_immutable_and_rejects_source_append(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    source = tmp_path / "results.jsonl"
    original = b'{"row":1}\n'
    source.write_bytes(original)
    source.chmod(0o600)
    snapshot = production._snapshot_results(source)
    try:
        with snapshot.path.open("rb") as handle:
            assert handle.read() == original
        with source.open("ab") as handle:
            handle.write(b'{"row":2}\n')
        with snapshot.path.open("rb") as handle:
            assert handle.read() == original
        with pytest.raises(
            production.ProductionCertificateError,
            match="^results_changed_during_audit$",
        ):
            snapshot.revalidate()
    finally:
        snapshot.close()


@pytest.mark.parametrize(
    "raw",
    (
        b"opaque-a\nopaque-a\n",
        b"opaque-a \nopaque-b\n",
        b"# comment\nopaque-a\n",
        b"opaque-a\tmetadata\nopaque-b\n",
    ),
)
def test_task_manifest_descriptor_parser_rejects_ambiguous_rows(raw: bytes) -> None:
    with pytest.raises(
        production.ProductionCertificateError,
        match="^expected_task_file_invalid$",
    ):
        production._expected_slugs_from_bytes(raw)


def test_directory_anchor_detects_run_path_replacement(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir(mode=0o700)
    run_dir.chmod(0o700)
    anchor = production._open_directory_anchor(run_dir)
    original = tmp_path / "original"
    run_dir.rename(original)
    run_dir.mkdir(mode=0o700)
    run_dir.chmod(0o700)
    try:
        with pytest.raises(production.ProductionCertificateError, match="run_dir_changed"):
            anchor.revalidate()
    finally:
        anchor.close()


def test_atomic_publication_failure_leaves_no_pass_certificate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path.chmod(0o700)
    original_fsync = production.os.fsync
    calls = 0

    def fail_directory_fsync(descriptor: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("synthetic fsync failure")
        original_fsync(descriptor)

    monkeypatch.setattr(production.os, "fsync", fail_directory_fsync)
    anchor = production._open_directory_anchor(tmp_path)
    try:
        with pytest.raises(
            production.ProductionCertificateError,
            match="checkpoint_publication_failed",
        ):
            production._publish_anchored_entry(
                anchor,
                production.CHECKPOINT_NAME,
                {"state": "passed"},
                authoritative=True,
            )
    finally:
        anchor.close()
    assert not (tmp_path / production.CHECKPOINT_NAME).exists()
    assert not list(tmp_path.glob(f".{production.CHECKPOINT_NAME}.*.tmp"))


def test_postcommit_fsync_failure_never_removes_or_reports_pass_as_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path.chmod(0o700)
    original_fsync = production.os.fsync
    calls = 0

    def fail_postcommit_fsync(descriptor: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 4:
            raise OSError("synthetic postcommit fsync failure")
        original_fsync(descriptor)

    monkeypatch.setattr(production.os, "fsync", fail_postcommit_fsync)
    anchor = production._open_directory_anchor(tmp_path)
    try:
        digest, raw = production._publish_anchored_entry(
            anchor,
            production.CHECKPOINT_NAME,
            {"state": "passed"},
            authoritative=True,
        )
    finally:
        anchor.close()
    checkpoint = tmp_path / production.CHECKPOINT_NAME
    assert checkpoint.read_bytes() == raw
    assert _sha256_bytes(raw) == digest
    assert stat.S_IMODE(checkpoint.stat().st_mode) == 0o444
    assert checkpoint.stat().st_nlink == 1


def test_completion_marker_is_published_last_and_failure_never_creates_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path.chmod(0o700)
    anchor = production._open_directory_anchor(tmp_path)
    original = production._publish_anchored_entry
    observed: list[str] = []

    def fail_completion(*args, **kwargs):
        name = args[1]
        observed.append(name)
        if name == production.CHECKPOINT_NAME:
            raise production.ProductionCertificateError("injected_completion_failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(production, "_publish_anchored_entry", fail_completion)
    try:
        with pytest.raises(
            production.ProductionCertificateError,
            match="injected_completion_failure",
        ):
            production._publish_certificate(
                anchor,
                {"state": "audited"},
                authorization={
                    "authorization_sha256": "a" * 64,
                    "run": {"eval_run_identity_sha256": "b" * 64},
                    "scheduler": {"job_id": "101"},
                },
            )
    finally:
        anchor.close()
    assert observed == [production.PAYLOAD_NAME, production.CHECKPOINT_NAME]
    assert (tmp_path / production.PAYLOAD_NAME).is_file()
    assert not (tmp_path / production.CHECKPOINT_NAME).exists()


@pytest.mark.parametrize(
    "claim",
    [
        {
            "established": True,
            "trace_certificate_sufficient": False,
            "required_downstream_artifacts": list(production.SFT_READINESS_REQUIREMENTS),
        },
        {
            "established": False,
            "trace_certificate_sufficient": True,
            "required_downstream_artifacts": list(production.SFT_READINESS_REQUIREMENTS),
        },
        {
            "established": False,
            "trace_certificate_sufficient": False,
            "required_downstream_artifacts": ["format_v3_export_manifest"],
        },
    ],
)
def test_rejects_claim_that_trace_certificate_alone_is_sft_ready(
    claim: dict[str, object],
) -> None:
    with pytest.raises(
        production.ProductionCertificateError,
        match="^sft_training_readiness_claim_invalid$",
    ):
        production._validate_sft_training_readiness_scope(claim)


def test_qualified_rollout_contract_rejects_short_timeout_or_non_vmvm() -> None:
    assert production.EXPECTED_FULL_TIMEOUTS == {
        "connect_timeout": production.eval_run_identity_module.KIMI_CONNECT_TIMEOUT_SECONDS,
        "finalize_timeout": production.eval_run_identity_module.KIMI_FINALIZE_TIMEOUT_SECONDS,
        "harness_request_timeout": production.eval_run_identity_module.KIMI_REQUEST_TIMEOUT_SECONDS,
        "request_timeout": production.eval_run_identity_module.KIMI_REQUEST_TIMEOUT_SECONDS,
        "rollout_timeout": production.eval_run_identity_module.KIMI_TIMEOUT_PROFILES["full"]["rollout_timeout"],
        "scoring_timeout": production.eval_run_identity_module.KIMI_SCORING_TIMEOUT_SECONDS,
        "session_timeout": production.eval_run_identity_module.KIMI_TIMEOUT_PROFILES["full"]["session_timeout"],
        "setup_timeout": production.eval_run_identity_module.KIMI_SETUP_TIMEOUT_SECONDS,
    }
    identity_contract = {
        "capture_model_io": True,
        "context_tokens": {
            "max_input_tokens": 262_144,
            "max_output_tokens": 262_144,
            "max_total_tokens": 262_144,
        },
        "model": "Kimi-K3",
        "num_rollouts": 1,
        "pass_at_1": True,
        "reasoning_effort": "max",
        "retain_traces": False,
        "sampling_max_tokens": 32_768,
        "thinking": {"enable_thinking": True, "preserve_thinking": True},
    }
    identity = {
        "contract": identity_contract,
        "source": {"vmvm_tb_v2_sha256": "a" * 64},
    }
    execution = {
        "http_max_connections": 24,
        "http_max_keepalive_connections": 24,
        "lease_start_concurrency": 4,
        "multiplex": 24,
        "rollout_concurrency": 24,
    }
    launch_contract = {
        **identity_contract,
        "execution": {
            key: execution[key]
            for key in (
                "http_max_connections",
                "http_max_keepalive_connections",
                "multiplex",
                "rollout_concurrency",
            )
        },
        "num_tasks": 2_500,
        "timeouts": dict(production.EXPECTED_FULL_TIMEOUTS),
        "vmvm": True,
    }
    assert (
        production._qualified_rollout_contract(
            identity,
            {"production": {"contract": launch_contract}},
            execution,
        )["runtime_provider"]
        == "vmvm"
    )

    launch_contract["timeouts"] = {
        **production.EXPECTED_FULL_TIMEOUTS,
        "rollout_timeout": 900,
    }
    with pytest.raises(
        production.ProductionCertificateError,
        match="^qualified_rollout_contract_invalid$",
    ):
        production._qualified_rollout_contract(
            identity,
            {"production": {"contract": launch_contract}},
            execution,
        )

    with pytest.raises(
        production.ProductionCertificateError,
        match="^eval_identity_execution_invalid$",
    ):
        production._require_execution(
            {
                "execution": {
                    **execution,
                    "runtime": {"type": "local"},
                    "vmvm_environment": {"lease_start_concurrency": 4},
                }
            }
        )


def test_wrapper_and_submitter_use_isolated_hash_bound_bootstrap() -> None:
    wrapper = (Path(production.__file__).with_name("run_trace_production_audit.sbatch")).read_text()
    submitter = (Path(production.__file__).with_name("submit_trace_production_audit.sh")).read_text()
    assert "submitted_wrapper=${BASH_SOURCE[0]}" in wrapper
    assert 'hash-object --no-filters -- "$path"' in wrapper
    assert 'digest_file "$submitted_wrapper"' in wrapper
    assert '"$python_path" -I -S -B -c "$loader"' in wrapper
    assert 'PYTHONPYCACHEPREFIX="$pycache_prefix"' in wrapper
    assert "PYTHONPATH" not in wrapper.split("/usr/bin/env -i", 1)[1]
    assert "uv run" not in wrapper
    submission_controller = (Path(production.__file__).with_name("trace_production_submit_control.py")).read_text()
    assert '"--export=NONE"' in submission_controller
    assert '"-",' in submission_controller
    assert "TRACE_SUBMITTER_SEALED_FD" in submitter
    assert "/usr/bin/sbatch" not in submitter
    assert '"/usr/bin/sbatch"' in submission_controller
    assert "BASH_ENV" in wrapper and "BASH_ENV" in submitter
    assert "BASH_FUNC_" in wrapper and "LD_" in wrapper and "UV_" in wrapper
