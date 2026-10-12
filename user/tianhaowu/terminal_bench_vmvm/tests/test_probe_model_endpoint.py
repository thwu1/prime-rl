from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import probe_model_endpoint as probe
import pytest


class _Transport:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict[str, str], bytes | None, float]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> probe.HttpResponse:
        self.requests.append((method, url, dict(headers), body, timeout))
        if method == "GET":
            return probe.HttpResponse(status_code=200, body=b'{"status":"ok"}')
        return probe.HttpResponse(
            status_code=200,
            body=json.dumps(
                {
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "content": "acknowledged",
                                "reasoning_content": "private reasoning",
                            },
                        }
                    ],
                    "usage": {"completion_tokens": 9},
                }
            ).encode(),
        )


def _profile(tmp_path: Path, *, max_tokens: int = 128) -> probe.EndpointProfile:
    return probe.EndpointProfile(
        name="synthetic",
        deployment_id="synthetic-deployment",
        model="Qwen3.8-2.4T-A95B",
        proxy_info=tmp_path / "proxy_info.json",
        deployment_spec=tmp_path / "spec.yaml",
        health_timeout_seconds=15,
        request_timeout_seconds=300,
        max_tokens=max_tokens,
    )


def test_qwen_profile_is_bounded_and_uses_shared_deployment_metadata() -> None:
    profile = probe.PROFILES[probe.DEFAULT_PROFILE]

    assert profile.name == "qwen38-2p4t"
    assert profile.deployment_id == "shared_qwen38_2p4t"
    assert profile.model == "Qwen3.8-2.4T-A95B"
    assert profile.proxy_info == Path(
        "/checkpoint/ram/shared/vllm_deployments_v2/shared_qwen38_2p4t/proxy_info.json"
    )
    assert profile.max_tokens >= 128
    assert profile.request_timeout_seconds == 300


def test_probe_uses_auth_and_session_header_but_returns_only_sanitized_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "do-not-emit-this-api-key"
    endpoint = SimpleNamespace(
        client_base_url="http://model.internal:8100/v1",
        api_key=secret,
        authority_sha256="a" * 64,
        proxy_info_sha256="b" * 64,
    )
    monkeypatch.setattr(probe, "load_deployment_endpoint", lambda *args, **kwargs: endpoint)
    transport = _Transport()

    result = probe.run_probe(_profile(tmp_path), transport=transport)

    assert [item[0] for item in transport.requests] == ["GET", "POST"]
    assert all(item[2]["Authorization"] == f"Bearer {secret}" for item in transport.requests)
    session_values = [item[2][probe.SESSION_HEADER] for item in transport.requests]
    assert session_values[0] == session_values[1]
    assert result["state"] == "passed"
    assert result["session_header"] == "x-session-id"
    assert result["max_tokens"] == 128
    assert result["completion"]["reasoning_present"] is True
    assert result["completion"]["reasoning_field"] == "reasoning_content"
    assert secret not in json.dumps(result)
    assert session_values[0] not in json.dumps(result)
    request_payload = json.loads(transport.requests[1][3] or b"")
    assert request_payload["max_tokens"] == 128


def test_probe_rejects_less_than_128_tokens(tmp_path: Path) -> None:
    with pytest.raises(probe.ModelEndpointProbeError, match="max_tokens_invalid"):
        probe.run_probe(_profile(tmp_path, max_tokens=127), transport=_Transport())


def test_cli_redacts_endpoint_and_transport_failures(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "secret-response-body"

    def fail(*args: object, **kwargs: object) -> dict[str, object]:
        del args, kwargs
        raise probe.ModelEndpointProbeError(secret)

    monkeypatch.setattr(probe, "run_probe", fail)
    assert probe.main([]) == 2
    captured = capsys.readouterr()
    assert secret not in captured.err
    assert json.loads(captured.err)["state"] == "failed"


def test_private_output_is_exclusive_and_mode_0600(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    output = tmp_path / "model-endpoint-probe.json"
    probe._publish(output, {"state": "passed"})

    assert output.stat().st_mode & 0o777 == 0o600
    assert json.loads(output.read_bytes()) == {"state": "passed"}
    with pytest.raises(FileExistsError):
        probe._publish(output, {"state": "passed"})
