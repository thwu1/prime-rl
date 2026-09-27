from __future__ import annotations

import hashlib
import json
from pathlib import Path

import attest_kimi_miniswe246_sandoq_small_smoke_format as attestor
import pytest


def _write_private(path: Path, value: object) -> bytes:
    body = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    path.write_bytes(body)
    path.chmod(0o600)
    return body


def _evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    receipt = tmp_path / "receipt.json"
    receipt_body = _write_private(
        receipt,
        {
            "schema_version": 2,
            "status": "diagnostic_passed",
            "model_calls": 3,
            "reasoning_content_retained": True,
            "shell_execution": True,
            "cleanup": True,
            "deployment": {
                "slurm_job_id": attestor.SOURCE_JOB_ID,
                "source_revision": attestor.SOURCE_REVISION,
                "router": {"endpoint_identifier": attestor.ENDPOINT_IDENTIFIER},
            },
        },
    )
    monkeypatch.setattr(attestor, "SOURCE_RECEIPT_SHA256", hashlib.sha256(receipt_body).hexdigest())

    requests = []
    responses = []
    messages = [{"role": "system", "content": "system"}, {"role": "user", "content": "task"}]
    for index in range(3):
        call = {
            "id": "reused",
            "type": "function",
            "function": {"name": "bash", "arguments": f'{{"cmd":"step-{index}"}}'},
        }
        requests.append(
            {
                "model": "Kimi-K3",
                "messages": [],
                "tools": [{"type": "function"}],
                "stream": False,
                "max_tokens": 512,
                "reasoning_effort": "max",
                "chat_template_kwargs": {"enable_thinking": True, "preserve_thinking": True},
                "parallel_tool_calls": False,
                "temperature": 1.0,
                "top_p": 1.0,
            }
        )
        responses.append(
            {
                "id": f"response-{index}",
                "model": "Kimi-K3",
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "reasoning": f"reasoning-{index}",
                            "tool_calls": [call],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }
        )
        messages.extend(
            [
                {
                    "role": "assistant",
                    "content": None,
                    "reasoning_content": f"reasoning-{index}",
                    "tool_calls": [call],
                },
                {"role": "tool", "content": "result", "tool_call_id": "reused"},
            ]
        )
    messages.append({"role": "exit", "content": "done"})
    raw_trace = tmp_path / "raw-trace.json"
    trace_body = _write_private(
        raw_trace,
        {
            "schema_version": 1,
            "model_requests": requests,
            "model_responses": responses,
            "program_stdout": "",
            "program_stderr": "",
            "trajectory": {"trajectory_format": "mini-swe-agent-1.1", "info": {}, "messages": messages},
        },
    )
    monkeypatch.setattr(attestor, "SOURCE_RAW_TRACE_SHA256", hashlib.sha256(trace_body).hexdigest())
    return receipt, raw_trace


def test_attestation_binds_exact_provider_reasoning_and_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt, raw_trace = _evidence(tmp_path, monkeypatch)
    output = tmp_path / "attestation.json"

    result = attestor.attest(receipt=receipt, raw_trace=raw_trace, output=output)

    assert result["state"] == "passed"
    assert result["response_kind"] == "exact_provider_json"
    assert result["reasoning_exact_parity"] == 3
    assert result["tool_call_exact_semantic_parity"] == 3
    assert output.stat().st_mode & 0o777 == 0o600


def test_attestation_rejects_reasoning_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt, raw_trace = _evidence(tmp_path, monkeypatch)
    value = json.loads(raw_trace.read_bytes())
    value["trajectory"]["messages"][2]["reasoning_content"] = "changed"
    trace_body = _write_private(raw_trace, value)
    monkeypatch.setattr(attestor, "SOURCE_RAW_TRACE_SHA256", hashlib.sha256(trace_body).hexdigest())

    with pytest.raises(attestor.SmokeFormatError, match="response_contract_invalid"):
        attestor.attest(receipt=receipt, raw_trace=raw_trace, output=tmp_path / "attestation.json")
