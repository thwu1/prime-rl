from __future__ import annotations

import fcntl
import hashlib
import json
from pathlib import Path

import pytest
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


def _trace(trace_id: str, task: str) -> dict:
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
        "nodes": [
            {
                "parent": None,
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
            }
        ],
    }


def _fixture(tmp_path: Path) -> tuple[Path, Path, str, dict]:
    run_dir = tmp_path / "run"
    inputs = run_dir / "inputs"
    inputs.mkdir(parents=True)
    task_file = tmp_path / "approved.txt"
    task_file.write_text("opaque-a\nopaque-b\n")
    task_sha256 = _sha256_bytes(task_file.read_bytes())
    results = run_dir / "results.jsonl"
    results.write_text(
        "\n".join(json.dumps(row) for row in (_trace("trace-a", "opaque-a"), _trace("trace-b", "opaque-b"))) + "\n"
    )
    config = run_dir / "config.toml"
    config.write_text('model = "Kimi-K3"\n')
    manifest = inputs / "manifest.json"
    manifest.write_text("{}\n")
    provenance = run_dir / "provenance.txt"
    provenance.write_text("eval_run_identity_sha256=placeholder\n")
    deployment_id = "deployment-test"
    deployment_dir = tmp_path / deployment_id
    deployment_dir.mkdir()
    spec = deployment_dir / "spec.yaml"
    spec.write_text("spec:\n  proxy:\n    config:\n      request_timeout: 7200\n      num_retries: 0\n")
    (deployment_dir / "proxy_litellm_config.yaml").write_text(
        "litellm_settings:\n  request_timeout: 7200\n  num_retries: 0\n"
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
        "eval_run_identity_sha256": "b" * 64,
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
    )
    write_guard_success_receipt(run_dir / "route_guard_success.json", receipt)
    return run_dir, task_file, task_sha256, envelope


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
    assert certificate["artifacts"]["proxy_info"] == certificate["endpoint"]["proxy_info"]
    assert certificate["audit_policy"]["model_io_contract"]["request_model"] == "Kimi-K3"
    assert "opaque-a" not in json.dumps(certificate)
    body = {key: value for key, value in certificate.items() if key != "smoke_checkpoint_sha256"}
    assert certificate["smoke_checkpoint_sha256"] == _sha256_bytes(
        json.dumps(body, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
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
    rows[0]["nodes"][0]["message"]["reasoning_content"] = ""
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
