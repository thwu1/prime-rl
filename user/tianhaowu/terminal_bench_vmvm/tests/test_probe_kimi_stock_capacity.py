from __future__ import annotations

import hashlib
import json
import stat
import threading
from pathlib import Path

import probe_kimi_stock_capacity as probe
import pytest


def _write_deployment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    root = tmp_path / probe.EXPECTED_DEPLOYMENT_ID
    endpoints = root / "endpoints"
    endpoints.mkdir(parents=True)
    endpoint_file = endpoints / "12345.json"
    endpoint_file.write_text(
        json.dumps(
            {
                "host": "stock-worker.invalid",
                "port": 8123,
                "started_at": "2026-09-27T02:22:00Z",
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )
    spec = root / "spec.yaml"
    spec.write_text("spec:\n  served_model_name: Kimi-K3\n  num_endpoints: 1\n")
    proxy_config = root / "proxy_litellm_config.yaml"
    proxy_config.write_text(
        "model_list:\n"
        "  - model_name: Kimi-K3\n"
        "    litellm_params:\n"
        "      model: openai/Kimi-K3\n"
        "      api_base: http://stock-worker.invalid:8123/v1\n"
        "      api_key: EMPTY\n"
    )
    monkeypatch.setattr(probe, "EXPECTED_SPEC_SHA256", hashlib.sha256(spec.read_bytes()).hexdigest())
    monkeypatch.setattr(
        probe,
        "EXPECTED_PROXY_CONFIG_SHA256",
        hashlib.sha256(proxy_config.read_bytes()).hexdigest(),
    )
    monkeypatch.setattr(probe, "DEFAULT_DEPLOYMENT_ROOT", root)
    return root, endpoint_file


def _metrics(*, waiting: int = 0, preemptions: int = 0, completed: int = 0) -> bytes:
    return (
        "\n".join(
            (
                "vllm:num_requests_running 0",
                f"vllm:num_requests_waiting {waiting}",
                f"vllm:num_preemptions_total {preemptions}",
                f"vllm:generation_tokens_total {1000 + completed * 8}",
                f"vllm:request_success_total {100 + completed}",
                f'vllm:kv_cache_usage_perc{{model_name="Kimi-K3"}} {0.01 + completed / 10000}',
            )
        )
        + "\n"
    ).encode()


def _completion(index: int, *, reasoning: bool = True) -> bytes:
    message: dict[str, object] = {
        "role": "assistant",
        "tool_calls": [
            {
                "id": f"call-{index}",
                "type": "function",
                "function": {
                    "name": probe.TOOL_NAME,
                    "arguments": json.dumps({"marker": probe.TOOL_MARKER}),
                },
            }
        ],
    }
    if reasoning:
        if index % 2:
            message["reasoning_content"] = f"PRIVATE_REASONING_CONTENT_{index}"
        elif index % 4:
            message["reasoning"] = [{"text": f"PRIVATE_RAW_REASONING_{index}"}]
        else:
            message["reasoning"] = f"PRIVATE_RAW_REASONING_{index}"
    return json.dumps(
        {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": message,
                }
            ],
            "model": probe.EXPECTED_MODEL,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


class FakeTransport:
    def __init__(
        self,
        *,
        after_waiting: int = 0,
        after_preemptions: int = 0,
        response_failure: int | None = None,
        transport_failure: int | None = None,
        missing_reasoning: int | None = None,
        endpoint_to_rotate: Path | None = None,
    ) -> None:
        self.after_waiting = after_waiting
        self.after_preemptions = after_preemptions
        self.response_failure = response_failure
        self.transport_failure = transport_failure
        self.missing_reasoning = missing_reasoning
        self.endpoint_to_rotate = endpoint_to_rotate
        self.metrics_calls = 0
        self.sessions: set[str] = set()
        self.lock = threading.Lock()

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> probe.HttpResponse:
        assert timeout >= 1
        if (method, path) == ("GET", "/metrics"):
            with self.lock:
                call = self.metrics_calls
                self.metrics_calls += 1
                completed = len(self.sessions)
            if call == 0:
                return probe.HttpResponse(200, _metrics())
            return probe.HttpResponse(
                200,
                _metrics(
                    waiting=self.after_waiting,
                    preemptions=self.after_preemptions,
                    completed=completed,
                ),
            )
        if (method, path) == ("GET", "/v1/models"):
            return probe.HttpResponse(200, b'{"data":[{"id":"Kimi-K3"}]}')
        assert (method, path) == ("POST", "/v1/chat/completions")
        assert body == probe.REQUEST_BODY
        session = headers[probe.SESSION_HEADER]
        index = int(session.rsplit("-", 1)[1])
        with self.lock:
            assert session not in self.sessions
            self.sessions.add(session)
        if index == self.transport_failure:
            raise OSError("PRIVATE_TRANSPORT_ERROR")
        if index == self.response_failure:
            return probe.HttpResponse(503, b"PRIVATE_HTTP_ERROR_BODY")
        if index == 0 and self.endpoint_to_rotate is not None:
            value = json.loads(self.endpoint_to_rotate.read_bytes())
            value["started_at"] = "2026-09-27T03:00:00Z"
            self.endpoint_to_rotate.write_text(json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n")
        return probe.HttpResponse(200, _completion(index, reasoning=index != self.missing_reasoning))


def _capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    transport: FakeTransport,
    *,
    concurrency: int = probe.DEFAULT_CONCURRENCY,
) -> tuple[dict[str, object], Path, str]:
    root, _endpoint = _write_deployment(tmp_path, monkeypatch)
    output_dir = tmp_path / "output"
    output_dir.mkdir(mode=0o700)
    output = output_dir / "receipt.json"
    receipt, receipt_sha256 = probe.capture_probe(
        root,
        output,
        concurrency=concurrency,
        request_timeout_seconds=1,
        metrics_timeout_seconds=1,
        transport=transport,
    )
    return receipt, output, receipt_sha256


def test_probe_writes_private_canonical_aggregate_and_accepts_raw_reasoning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = FakeTransport()
    receipt, output, receipt_sha256 = _capture(tmp_path, monkeypatch, transport)
    body = output.read_bytes()

    assert receipt["state"] == "passed"
    assert receipt["concurrency"] == {"client_peak_in_flight": 24, "configured": 24}
    assert receipt["completions"]["successful"] == 24
    assert receipt["completions"]["reasoning_present"] == 24
    assert receipt["completions"]["raw_reasoning_present"] == 12
    assert receipt["completions"]["tool_calls_total"] == 24
    assert receipt["metrics"]["deltas"]["preemptions"] == 0
    assert receipt["endpoint_unchanged"] is True
    assert len(transport.sessions) == 24
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert output.stat().st_nlink == 1
    assert receipt_sha256 == hashlib.sha256(body).hexdigest()
    assert body == probe._canonical_json(json.loads(body)) + b"\n"
    assert b"PRIVATE_" not in body
    assert b"stock-worker.invalid" not in body
    assert b"api_key" not in body


def test_probe_persists_only_counts_for_response_and_transport_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = FakeTransport(response_failure=0, transport_failure=1, missing_reasoning=2)
    receipt, output, _digest = _capture(tmp_path, monkeypatch, transport)

    assert receipt["state"] == "failed"
    assert receipt["completions"]["attempted"] == 24
    assert receipt["completions"]["successful"] == 21
    assert receipt["completions"]["response_errors"] == 2
    assert receipt["completions"]["transport_errors"] == 1
    assert receipt["completions"]["reasoning_present"] == 21
    assert b"PRIVATE_HTTP_ERROR_BODY" not in output.read_bytes()
    assert b"PRIVATE_TRANSPORT_ERROR" not in output.read_bytes()


def test_probe_permits_64_concurrent_requests(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    transport = FakeTransport()
    receipt, _output, _digest = _capture(tmp_path, monkeypatch, transport, concurrency=64)

    assert receipt["state"] == "passed"
    assert receipt["concurrency"] == {"client_peak_in_flight": 64, "configured": 64}
    assert receipt["completions"]["successful"] == 64
    assert len(transport.sessions) == 64


@pytest.mark.parametrize(
    ("after_waiting", "after_preemptions"),
    ((1, 0), (0, 1)),
)
def test_probe_fails_on_queue_or_preemption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    after_waiting: int,
    after_preemptions: int,
) -> None:
    receipt, _output, _digest = _capture(
        tmp_path,
        monkeypatch,
        FakeTransport(after_waiting=after_waiting, after_preemptions=after_preemptions),
    )

    assert receipt["state"] == "failed"
    assert receipt["metrics"]["after"]["waiting"] == after_waiting
    assert receipt["metrics"]["deltas"]["preemptions"] == after_preemptions


def test_probe_fails_when_endpoint_file_changes_during_requests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, endpoint = _write_deployment(tmp_path, monkeypatch)
    output_dir = tmp_path / "output"
    output_dir.mkdir(mode=0o700)
    receipt, _digest = probe.capture_probe(
        root,
        output_dir / "receipt.json",
        concurrency=24,
        request_timeout_seconds=1,
        metrics_timeout_seconds=1,
        transport=FakeTransport(endpoint_to_rotate=endpoint),
    )

    assert receipt["state"] == "failed"
    assert receipt["endpoint_unchanged"] is False
    assert receipt["completions"]["successful"] == 24


def test_binding_rejects_multiple_endpoints_and_proxy_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, endpoint = _write_deployment(tmp_path, monkeypatch)
    second = endpoint.with_name("12346.json")
    second.write_bytes(endpoint.read_bytes())
    with pytest.raises(probe.KimiStockCapacityProbeError, match="endpoint_membership_invalid"):
        probe._load_binding(root)

    second.unlink()
    proxy_config = root / "proxy_litellm_config.yaml"
    proxy_config.write_text(proxy_config.read_text().replace(":8123/v1", ":8124/v1"))
    monkeypatch.setattr(
        probe,
        "EXPECTED_PROXY_CONFIG_SHA256",
        hashlib.sha256(proxy_config.read_bytes()).hexdigest(),
    )
    with pytest.raises(probe.KimiStockCapacityProbeError, match="proxy_config_invalid"):
        probe._load_binding(root)


def test_atomic_publication_is_mode_0600_and_never_overwrites(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir(mode=0o700)
    output = output_dir / "receipt.json"
    first = {"kind": probe.KIND, "state": "failed"}
    probe._publish(output, first)
    original = output.read_bytes()

    with pytest.raises(probe.KimiStockCapacityProbeError, match="output_path_invalid"):
        probe._publish(output, {"kind": probe.KIND, "state": "passed"})

    assert output.read_bytes() == original
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert not list(output_dir.glob(".*.stage-*"))


def test_cli_defaults_to_24_and_permits_only_64_as_alternate(tmp_path: Path) -> None:
    output = tmp_path / "receipt.json"
    assert probe._parser().parse_args(["--output", str(output)]).concurrency == 24
    assert probe._parser().parse_args(["--concurrency", "64", "--output", str(output)]).concurrency == 64
    with pytest.raises(SystemExit):
        probe._parser().parse_args(["--concurrency", "32", "--output", str(output)])


def test_cli_returns_nonzero_and_prints_only_safe_summary_for_failed_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        probe,
        "capture_probe",
        lambda *_args, **_kwargs: ({"state": "failed"}, "a" * 64),
    )

    assert probe.main(["--output", str(tmp_path / "receipt.json")]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "kind": probe.KIND,
        "receipt_sha256": "a" * 64,
        "state": "failed",
    }
