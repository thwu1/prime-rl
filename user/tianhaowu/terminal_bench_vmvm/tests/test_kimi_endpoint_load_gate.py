from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import kimi_endpoint_load_gate as gate
import pytest


def _urls() -> tuple[str, ...]:
    return tuple(f"http://worker-{index:02d}.invalid:{8000 + index}" for index in range(24))


def _manifest() -> dict[str, object]:
    return {"endpoint_bundle_sha256": "a" * 64}


class FakeFetcher:
    def __init__(
        self,
        *,
        waiting: int = 0,
        preemption_change: bool = False,
        cache: float = 0.01,
        concentrated_running: bool = False,
        omit_cache: bool = False,
        zero_prefix: bool = False,
    ) -> None:
        self.round = 0
        self.waiting = waiting
        self.preemption_change = preemption_change
        self.cache = cache
        self.concentrated_running = concentrated_running
        self.omit_cache = omit_cache
        self.zero_prefix = zero_prefix

    def sleep(self, _seconds: float) -> None:
        self.round = 1

    def __call__(self, url: str, _timeout: float) -> tuple[int, bytes]:
        if url.endswith("/health"):
            return 200, b"\n"
        worker = int(url.split("worker-", 1)[1].split(".", 1)[0])
        running = 4 if self.concentrated_running and worker == 0 else int(worker < 4)
        waiting = int(worker == 0) * self.waiting
        preemptions = int(self.preemption_change and self.round == 1 and worker == 0)
        generation = 1000 + worker + self.round
        successes = 100 + worker + self.round
        prefix_hits = 0 if self.zero_prefix else 800 + worker + self.round
        prefix_queries = 0 if self.zero_prefix else 1000 + worker + self.round
        metrics = [
            f"vllm:num_requests_running {running}",
            f"vllm:num_requests_waiting {waiting}",
            f"vllm:num_preemptions_total {preemptions}",
            f"vllm:generation_tokens_total {generation}",
            f"vllm:request_success_total {successes}",
            f"vllm:prefix_cache_hits_total {prefix_hits}",
            f"vllm:prefix_cache_queries_total {prefix_queries}",
        ]
        if not self.omit_cache:
            metrics.append(f"vllm:kv_cache_usage_perc {self.cache}")
        body = "\n".join(metrics).encode()
        return 200, body


def _capture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fetcher: FakeFetcher) -> dict[str, object]:
    os.chmod(tmp_path, 0o700)
    monkeypatch.setattr(
        gate,
        "_load_bound_generation",
        lambda *_args: (_manifest(), _urls()),
    )
    return gate.capture_load_gate(
        manifest_path=tmp_path / "direct_kimi_workers.json",
        worker_urls_path=tmp_path / "worker_urls.private.txt",
        manifest_sha256="b" * 64,
        interval_seconds=1,
        request_timeout_seconds=1,
        output=tmp_path / "load_gate.json",
        fetcher=fetcher,
        sleeper=fetcher.sleep,
        clock=lambda: 1234567890.0,
    )


def test_capture_is_aggregate_only_and_mode_0600(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fetcher = FakeFetcher()
    receipt = _capture(tmp_path, monkeypatch, fetcher)
    output = tmp_path / "load_gate.json"
    persisted = json.loads(output.read_bytes())

    assert receipt == persisted
    assert receipt["state"] == "passed"
    assert receipt["worker_count"] == 24
    assert [snapshot["running"] for snapshot in receipt["snapshots"]] == [4, 4]
    assert [snapshot["waiting"] for snapshot in receipt["snapshots"]] == [0, 0]
    assert receipt["deltas"] == {
        "generation_tokens": 24,
        "preemptions": 0,
        "successful_requests": 24,
    }
    assert stat_mode(output) == 0o600
    serialized = json.dumps(receipt, sort_keys=True)
    assert "worker-" not in serialized
    assert ".invalid" not in serialized

    assert (
        gate.validate_load_gate(
            output,
            expected_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
            manifest_sha256="b" * 64,
            endpoint_bundle_sha256="a" * 64,
            maximum_age_seconds=60,
            clock=lambda: 1234567891.0,
        )
        == receipt
    )


def test_zero_prefix_counters_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    receipt = _capture(tmp_path, monkeypatch, FakeFetcher(zero_prefix=True))
    output = tmp_path / "load_gate.json"
    assert all(snapshot["prefix_cache_hit_rate"] is None for snapshot in receipt["snapshots"])
    assert (
        gate.validate_load_gate(
            output,
            expected_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
            manifest_sha256="b" * 64,
            endpoint_bundle_sha256="a" * 64,
        )
        == receipt
    )


def test_validator_rejects_stale_or_tampered_per_worker_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _capture(tmp_path, monkeypatch, FakeFetcher())
    output = tmp_path / "load_gate.json"
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    with pytest.raises(gate.KimiEndpointLoadGateError, match="load_gate_invalid"):
        gate.validate_load_gate(
            output,
            expected_sha256=digest,
            manifest_sha256="b" * 64,
            endpoint_bundle_sha256="a" * 64,
            maximum_age_seconds=60,
            clock=lambda: 1234568000.0,
        )

    value = json.loads(output.read_bytes())
    value["snapshots"][0]["running_per_worker_max"] = 2
    output.chmod(0o600)
    output.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
    output.chmod(0o600)
    with pytest.raises(gate.KimiEndpointLoadGateError, match="load_gate_invalid"):
        gate.validate_load_gate(
            output,
            expected_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
            manifest_sha256="b" * 64,
            endpoint_bundle_sha256="a" * 64,
        )


@pytest.mark.parametrize(
    ("digest", "manifest", "bundle"),
    (
        ("f" * 64, "b" * 64, "a" * 64),
        (None, "f" * 64, "a" * 64),
        (None, "b" * 64, "f" * 64),
    ),
)
def test_validator_rejects_changed_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    digest: str | None,
    manifest: str,
    bundle: str,
) -> None:
    _capture(tmp_path, monkeypatch, FakeFetcher())
    output = tmp_path / "load_gate.json"

    with pytest.raises(gate.KimiEndpointLoadGateError, match="load_gate_invalid"):
        gate.validate_load_gate(
            output,
            expected_sha256=digest or hashlib.sha256(output.read_bytes()).hexdigest(),
            manifest_sha256=manifest,
            endpoint_bundle_sha256=bundle,
        )


def test_validator_rejects_non_private_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _capture(tmp_path, monkeypatch, FakeFetcher())
    output = tmp_path / "load_gate.json"
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.chmod(0o644)

    with pytest.raises(gate.KimiEndpointLoadGateError, match="load_gate_invalid"):
        gate.validate_load_gate(
            output,
            expected_sha256=digest,
            manifest_sha256="b" * 64,
            endpoint_bundle_sha256="a" * 64,
        )


@pytest.mark.parametrize(
    ("section", "key", "value"),
    (
        ("snapshot", "waiting", False),
        ("snapshot", "successful_requests", "1"),
        ("snapshot", "kv_cache_usage_mean", None),
        ("delta", "generation_tokens", "1"),
    ),
)
def test_validator_rejects_malformed_aggregate_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    section: str,
    key: str,
    value: object,
) -> None:
    _capture(tmp_path, monkeypatch, FakeFetcher())
    output = tmp_path / "load_gate.json"
    payload = json.loads(output.read_bytes())
    target = payload["snapshots"][0] if section == "snapshot" else payload["deltas"]
    target[key] = value
    output.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    output.chmod(0o600)

    with pytest.raises(gate.KimiEndpointLoadGateError, match="load_gate_invalid"):
        gate.validate_load_gate(
            output,
            expected_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
            manifest_sha256="b" * 64,
            endpoint_bundle_sha256="a" * 64,
        )


def test_rejects_any_waiting_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(gate.KimiEndpointLoadGateError, match="endpoint_not_low_load"):
        _capture(tmp_path, monkeypatch, FakeFetcher(waiting=1))
    assert not (tmp_path / "load_gate.json").exists()


def test_rejects_preemption_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(gate.KimiEndpointLoadGateError, match="worker_preemption_changed"):
        _capture(tmp_path, monkeypatch, FakeFetcher(preemption_change=True))
    assert not (tmp_path / "load_gate.json").exists()


def test_rejects_high_cache_use(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(gate.KimiEndpointLoadGateError, match="endpoint_not_low_load"):
        _capture(tmp_path, monkeypatch, FakeFetcher(cache=0.051))
    assert not (tmp_path / "load_gate.json").exists()


def test_rejects_concentrated_preexisting_load(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(gate.KimiEndpointLoadGateError, match="endpoint_not_low_load"):
        _capture(tmp_path, monkeypatch, FakeFetcher(concentrated_running=True))
    assert not (tmp_path / "load_gate.json").exists()


def test_rejects_missing_cache_metric(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(gate.KimiEndpointLoadGateError, match="worker_metrics_missing"):
        _capture(tmp_path, monkeypatch, FakeFetcher(omit_cache=True))
    assert not (tmp_path / "load_gate.json").exists()


def test_metric_parser_requires_complete_counters() -> None:
    with pytest.raises(gate.KimiEndpointLoadGateError, match="worker_metrics_missing"):
        gate._parse_metrics(b"vllm:num_requests_running 0\n")


def test_fetch_rejects_redirected_final_url(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def geturl(self) -> str:
            return "http://different.invalid/metrics"

        def read(self, _limit: int) -> bytes:
            return b""

    class Opener:
        def open(self, _url: str, timeout: float):
            assert timeout == 1
            return Response()

    def build_opener(*handlers: object) -> Opener:
        assert any(isinstance(handler, gate._NoRedirectHandler) for handler in handlers)
        return Opener()

    monkeypatch.setattr(gate.urllib.request, "build_opener", build_opener)

    with pytest.raises(gate.KimiEndpointLoadGateError, match="worker_response_invalid"):
        gate._fetch("http://worker.invalid/metrics", 1)


def stat_mode(path: Path) -> int:
    return path.stat().st_mode & 0o777
