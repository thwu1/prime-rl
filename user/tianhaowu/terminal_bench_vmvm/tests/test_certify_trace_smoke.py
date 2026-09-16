from __future__ import annotations

import fcntl
import hashlib
import json
from pathlib import Path

import pytest
from certify_trace_smoke import SmokeCertificateError, certify_smoke


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
                }
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
        "\n".join(
            json.dumps(row)
            for row in (_trace("trace-a", "opaque-a"), _trace("trace-b", "opaque-b"))
        )
        + "\n"
    )
    config = run_dir / "config.toml"
    config.write_text('model = "Kimi-K3"\n')
    manifest = inputs / "manifest.json"
    manifest.write_text("{}\n")
    provenance = run_dir / "provenance.txt"
    provenance.write_text("eval_run_identity_sha256=placeholder\n")
    readiness = tmp_path / "readiness.json"
    readiness.write_text('{"state":"passed"}\n')
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
            "id": "deployment-test",
            "spec": {"path": str(tmp_path / "spec.yaml"), "sha256": "a" * 64},
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
