from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from deployment_endpoint import load_deployment_endpoint
from inference_route_generation import route_generation_from_status_endpoints
from probe_inference_routes import _backend_identifier
from wait_for_inference_routes import (
    GateConfig,
    GateError,
    ProcessResult,
    _child_environment,
    _status_command,
    run_gate,
)


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


class FakeRunner:
    def __init__(self, results: Sequence[ProcessResult]) -> None:
        self.results = list(results)
        self.calls: list[tuple[list[str], float]] = []

    def __call__(self, argv: Sequence[str], timeout: float) -> ProcessResult:
        self.calls.append((list(argv), timeout))
        if not self.results:
            raise AssertionError("unexpected command")
        result = self.results.pop(0)
        if "--proxy-info-sha256" in argv and result.stdout:
            payload = json.loads(result.stdout)
            if "endpoint_authority_sha256" not in payload:
                endpoint = load_deployment_endpoint(
                    Path(argv[argv.index("--proxy-info") + 1]),
                    deployment_id=argv[argv.index("--deployment-id") + 1],
                    expected_model=argv[argv.index("--model") + 1],
                    deployment_spec=Path(argv[argv.index("--deployment-spec") + 1]),
                    expected_proxy_info_sha256=argv[argv.index("--proxy-info-sha256") + 1],
                )
                payload["endpoint_authority_sha256"] = endpoint.authority_sha256
                result = ProcessResult(result.returncode, json.dumps(payload), result.stderr)
        return result


def _status(
    *,
    phase: str = "serving",
    desired: Any = 24,
    ready: Any = 24,
    running_not_ready: Any = 0,
    pending: Any = 0,
    deployment: str = "test-deployment",
    job_ids: Sequence[str] | None = None,
    endpoint_started_at: str = "2026-09-17T01:00:00Z",
    coord_job_id: str = "900",
    coord_started_at: str = "2026-09-17T00:00:00Z",
    coord_ticks: Any = 10,
    proxy_job_id: str = "12345",
    proxy_first_ready_at: str = "2026-09-17T00:30:00Z",
    schema_version: Any = 4,
) -> ProcessResult:
    endpoint_count = desired if isinstance(desired, int) and not isinstance(desired, bool) else 24
    if job_ids is None:
        job_ids = [str(1000 + index) for index in range(endpoint_count)]
    payload = {
        "schema_version": schema_version,
        "deployment_id": deployment,
        "phase": phase,
        "terminal_reason": None,
        "coord": {
            "jobid": coord_job_id,
            "started_at": coord_started_at,
            "ticks_completed": coord_ticks,
        },
        "endpoints_summary": {
            "desired": desired,
            "ready": ready,
            "running_not_ready": running_not_ready,
            "pending": pending,
        },
        "endpoints": [
            {
                "jobid": job_id,
                "host": f"worker-{index}",
                "port": 8000 + index,
                "slurm_state": "RUNNING",
                "sub_state": "ready",
                "started_at": endpoint_started_at,
            }
            for index, job_id in enumerate(job_ids)
        ],
        # These fields must never be copied into the artifact.
        "proxy": {
            "jobid": proxy_job_id,
            "slurm_state": "RUNNING",
            "first_ready_at": proxy_first_ready_at,
            "url": "http://private-proxy:8100",
            "api_key": "status-secret",
        },
        "spec": {"future_secret": "do-not-copy"},
    }
    return ProcessResult(0 if phase == "serving" else 1, json.dumps(payload))


def _probe(
    *,
    ok: bool = True,
    returncode: int | None = None,
    endpoint_authority_sha256: str | None = None,
    backends: Sequence[str] | None = None,
) -> ProcessResult:
    if backends is None:
        backends = sorted(
            f"backend-sha256:{hashlib.sha256(f'http://worker-{index}:{8000 + index}/v1'.encode()).hexdigest()}"
            for index in range(24)
        )
    payload = {
        "ok": ok,
        "coverage": {
            "ok": ok,
            "expected_routes": len(backends),
            "discovered_routes": len(backends),
            "backends": list(backends),
        },
        "requests": {"ok": ok, "failed": 0 if ok else 1},
        "future_api_key": "not-a-known-key-name",
        "failure": "Bearer unit-test-secret" if not ok else None,
    }
    if endpoint_authority_sha256 is not None:
        payload["endpoint_authority_sha256"] = endpoint_authority_sha256
    return ProcessResult(returncode if returncode is not None else (0 if ok else 1), json.dumps(payload))


def _backends(count: int) -> list[str]:
    return sorted(
        f"backend-sha256:{hashlib.sha256(f'http://worker-{index}:{8000 + index}/v1'.encode()).hexdigest()}"
        for index in range(count)
    )


def _config(tmp_path: Path, **overrides: Any) -> GateConfig:
    model = str(overrides.get("model", "Kimi-K3"))
    request_timeout = 43_200 if model == "Kimi-K3" else 7_200
    serve_sh = tmp_path / "serve.sh"
    probe_script = tmp_path / "probe.py"
    serve_sh.touch()
    probe_script.touch()
    deployment_dir = tmp_path / "test-deployment"
    deployment_dir.mkdir()
    spec = deployment_dir / "spec.yaml"
    spec.write_text(f"spec:\n  proxy:\n    config:\n      request_timeout: {request_timeout}\n      num_retries: 0\n")
    (deployment_dir / "proxy_litellm_config.yaml").write_text(
        f"litellm_settings:\n  request_timeout: {request_timeout}\n  num_retries: 0\n"
    )
    proxy_info = deployment_dir / "proxy_info.json"
    proxy_info.write_text(
        json.dumps(
            {
                "host": "proxy-info-url",
                "port": 8100,
                "url": "http://proxy-info-url:8100",
                "api_key": "unit-test-secret",
                "model": model,
                "proxy_jobid": "12345",
                "extras": {
                    "proxy_type": "litellm",
                    "prometheus_port": 8101,
                    "sticky": True,
                    "sticky_ttl": 900,
                    "redis_port": 6379,
                },
            }
        )
    )
    values: dict[str, Any] = {
        "deployment": "test-deployment",
        "model": model,
        "expected_spec_sha256": hashlib.sha256(spec.read_bytes()).hexdigest(),
        "serve_sh": serve_sh,
        "probe_script": probe_script,
        "spec": spec,
        "proxy_info": proxy_info,
        "output": tmp_path / "gate.json",
        "poll_interval": 1.0,
        "wait_timeout": 10.0,
    }
    values.update(overrides)
    return GateConfig(**values)


def _run(config: GateConfig, runner: FakeRunner, clock: FakeClock) -> dict[str, Any]:
    return run_gate(
        config,
        runner=runner,
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
        emit=lambda _message: None,
    )


def test_three_exact_polls_run_strict_probe_and_write_redacted_artifact(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    runner = FakeRunner(
        [
            _status(coord_ticks=10),
            _status(coord_ticks=11),
            _status(coord_ticks=12),
            _probe(),
            _status(coord_ticks=13),
        ]
    )
    clock = FakeClock()

    artifact = _run(config, runner, clock)

    assert artifact["state"] == "passed"
    assert artifact["polls"] == 3
    assert artifact["consecutive_ready_polls"] == 3
    assert [route["slurm_job_id"] for route in artifact["serving_route_generation"]["routes"]] == [
        str(1000 + index) for index in range(24)
    ]
    assert artifact["last_status"]["serving_route_generation"] == artifact["serving_route_generation"]
    assert artifact["proxy_info_readable"] is True
    assert artifact["observed_spec_sha256"] == config.expected_spec_sha256
    persisted = config.resolved_output().read_text()
    assert json.loads(persisted) == artifact
    assert "unit-test-secret" not in persisted
    assert "status-secret" not in persisted
    assert "do-not-copy" not in persisted
    assert "http://proxy-info-url:8100" not in persisted
    assert artifact["endpoint"]["kind"] == "deployment_local_proxy_info"
    assert artifact["endpoint"]["proxy_info"]["path"] == str(config.resolved_proxy_info().resolve())
    assert artifact["probe"]["endpoint_authority_sha256"] == artifact["endpoint"]["authority_sha256"]
    assert "proxy_base_url" not in artifact["probe"]
    assert artifact["probe"]["future_api_key"] == "<redacted>"
    assert config.resolved_output().stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob(".gate.json.*.tmp"))

    status_argv = runner.calls[0][0]
    assert status_argv == _status_command(config)
    probe_argv = runner.calls[-2][0]
    assert probe_argv[:2] == [sys.executable, str(config.probe_script)]
    assert probe_argv[probe_argv.index("--proxy-info-sha256") + 1] == artifact["endpoint"]["proxy_info"]["sha256"]
    assert probe_argv[probe_argv.index("--deployment-id") + 1] == config.deployment
    assert probe_argv[probe_argv.index("--deployment-spec") + 1] == str(config.resolved_spec())
    assert probe_argv[probe_argv.index("--expected-routes") + 1] == "24"
    assert probe_argv[probe_argv.index("--requests") + 1] == "192"
    assert probe_argv[probe_argv.index("--concurrency") + 1] == "24"
    assert "--require-reasoning" in probe_argv
    assert "--allow-unverified-affinity" not in probe_argv
    assert "--skip-health" not in probe_argv
    assert all("logprob" not in argument for argument in probe_argv)
    assert "return_token_ids" not in probe_argv


def test_qwen_readiness_keeps_7200_policy_and_crossed_kimi_policy_fails(tmp_path: Path) -> None:
    qwen_root = tmp_path / "qwen"
    qwen_root.mkdir()
    qwen = _config(qwen_root, model="Qwen3-Coder-480B-A35B-Instruct-FP8")
    runner = FakeRunner(
        [
            _status(coord_ticks=10),
            _status(coord_ticks=11),
            _status(coord_ticks=12),
            _probe(),
            _status(coord_ticks=13),
        ]
    )
    artifact = _run(qwen, runner, FakeClock())
    assert artifact["proxy_policy"]["request_timeout"] == 7_200

    crossed_root = tmp_path / "crossed"
    crossed_root.mkdir()
    crossed = _config(crossed_root)
    crossed.resolved_spec().write_text(
        crossed.resolved_spec().read_text().replace("request_timeout: 43200", "request_timeout: 7200")
    )
    crossed = GateConfig(
        **{
            **crossed.__dict__,
            "expected_spec_sha256": hashlib.sha256(crossed.resolved_spec().read_bytes()).hexdigest(),
        }
    )
    with pytest.raises(GateError, match="deployment_proxy_policy_invalid"):
        _run(crossed, FakeRunner([]), FakeClock())


def test_nonready_poll_resets_consecutive_streak(tmp_path: Path) -> None:
    config = _config(tmp_path)
    booting = _status(
        phase="booting",
        ready=23,
        running_not_ready=1,
        coord_ticks=11,
    )
    runner = FakeRunner(
        [
            _status(coord_ticks=10),
            booting,
            _status(coord_ticks=12),
            _status(coord_ticks=13),
            _status(coord_ticks=14),
            _probe(),
            _status(coord_ticks=15),
        ]
    )
    clock = FakeClock()

    artifact = _run(config, runner, clock)

    assert artifact["state"] == "passed"
    assert artifact["polls"] == 5
    assert artifact["consecutive_ready_polls"] == 3


def test_endpoint_job_rotation_resets_ready_streak(tmp_path: Path) -> None:
    config = _config(tmp_path, expected_routes=2, consecutive_polls=2)
    generation_a = _status(desired=2, ready=2, job_ids=["100", "101"], coord_ticks=10)
    generation_b = _status(desired=2, ready=2, job_ids=["200", "201"], coord_ticks=11)
    runner = FakeRunner(
        [
            generation_a,
            generation_b,
            _status(desired=2, ready=2, job_ids=["200", "201"], coord_ticks=12),
            _probe(backends=_backends(2)),
            _status(desired=2, ready=2, job_ids=["200", "201"], coord_ticks=13),
        ]
    )

    artifact = _run(config, runner, FakeClock())

    assert artifact["polls"] == 3
    assert [route["slurm_job_id"] for route in artifact["serving_route_generation"]["routes"]] == ["200", "201"]


@pytest.mark.parametrize(
    ("changed", "field"),
    [
        (
            {"endpoint_started_at": "2026-09-17T01:01:00Z"},
            "routes",
        ),
        (
            {"coord_started_at": "2026-09-17T00:01:00Z"},
            "coordinator",
        ),
    ],
)
def test_process_incarnation_rotation_resets_ready_streak(
    tmp_path: Path,
    changed: dict[str, str],
    field: str,
) -> None:
    config = _config(tmp_path, expected_routes=2, consecutive_polls=2)
    generation_a = _status(desired=2, ready=2, job_ids=["100", "101"], coord_ticks=10)
    runner = FakeRunner(
        [
            generation_a,
            _status(desired=2, ready=2, job_ids=["100", "101"], coord_ticks=11, **changed),
            _status(desired=2, ready=2, job_ids=["100", "101"], coord_ticks=12, **changed),
            _probe(backends=_backends(2)),
            _status(desired=2, ready=2, job_ids=["100", "101"], coord_ticks=13, **changed),
        ]
    )

    artifact = _run(config, runner, FakeClock())

    assert artifact["polls"] == 3
    assert field in artifact["serving_route_generation"]


def test_coordinator_tick_regression_fails_closed(tmp_path: Path) -> None:
    config = _config(tmp_path, consecutive_polls=3)
    runner = FakeRunner([_status(coord_ticks=10), _status(coord_ticks=9)])

    with pytest.raises(GateError, match="^coordinator_ticks_regressed$"):
        _run(config, runner, FakeClock())


def test_frozen_coordinator_tick_fails_closed(tmp_path: Path) -> None:
    config = _config(tmp_path, consecutive_polls=3)
    runner = FakeRunner([_status(coord_ticks=10), _status(coord_ticks=10)])

    with pytest.raises(GateError, match="^coordinator_ticks_not_advancing$"):
        _run(config, runner, FakeClock())


def test_frozen_coordinator_tick_after_probe_fails_closed(tmp_path: Path) -> None:
    config = _config(tmp_path, consecutive_polls=1)
    runner = FakeRunner([_status(coord_ticks=10), _probe(), _status(coord_ticks=10)])

    with pytest.raises(GateError, match="^coordinator_ticks_not_advancing$"):
        _run(config, runner, FakeClock())


def test_proxy_status_job_must_match_proxy_info(tmp_path: Path) -> None:
    config = _config(tmp_path, consecutive_polls=1)
    runner = FakeRunner([_status(proxy_job_id="54321")])

    with pytest.raises(GateError, match="^proxy_job_id_mismatch$"):
        _run(config, runner, FakeClock())


def test_endpoint_job_rotation_after_probe_fails_closed(tmp_path: Path) -> None:
    config = _config(tmp_path, expected_routes=2, consecutive_polls=1)
    generation_a = _status(desired=2, ready=2, job_ids=["100", "101"])
    generation_b = _status(desired=2, ready=2, job_ids=["200", "201"])
    runner = FakeRunner([generation_a, _probe(backends=_backends(2)), generation_b])

    with pytest.raises(GateError, match="^serving_route_generation_changed$"):
        _run(config, runner, FakeClock())

    artifact = json.loads(config.resolved_output().read_text())
    assert artifact["state"] == "failed"
    assert artifact["reason"] == "serving_route_generation_changed"


def test_probe_backend_set_must_match_status_routes(tmp_path: Path) -> None:
    config = _config(tmp_path, consecutive_polls=1)
    backends = _backends(24)
    backends[-1] = f"backend-sha256:{'f' * 64}"
    runner = FakeRunner([_status(), _probe(backends=backends)])

    with pytest.raises(GateError, match="^probe_serving_routes_mismatch$"):
        _run(config, runner, FakeClock())


def test_duplicate_endpoint_job_ids_fail_before_probe(tmp_path: Path) -> None:
    config = _config(tmp_path, consecutive_polls=1)
    runner = FakeRunner([_status(job_ids=["100"] * 24)])

    with pytest.raises(GateError, match="^malformed_status_serving_endpoints$"):
        _run(config, runner, FakeClock())

    assert len(runner.calls) == 1


def test_status_backend_hash_matches_probe_identifier() -> None:
    endpoint = {
        "jobid": "12345",
        "host": "worker-0",
        "port": 8000,
        "slurm_state": "RUNNING",
        "sub_state": "ready",
        "started_at": "2026-09-17T01:00:00Z",
    }
    generation = route_generation_from_status_endpoints(
        [endpoint],
        {
            "jobid": "900",
            "started_at": "2026-09-17T00:00:00Z",
            "ticks_completed": 10,
        },
        {
            "jobid": "12345",
            "slurm_state": "RUNNING",
            "first_ready_at": "2026-09-17T00:30:00Z",
        },
    )

    assert generation["routes"][0]["backend_sha256"] == _backend_identifier("http://worker-0:8000/v1")[0]


@pytest.mark.parametrize(
    ("result", "reason"),
    [
        (ProcessResult(2, _status().stdout), "status_command_failed"),
        (ProcessResult(0, "not-json"), "malformed_status_json"),
        (_status(phase="failed"), "terminal_deployment"),
        (_status(phase="FAILED"), "terminal_deployment"),
        (_status(ready=True, pending=23), "malformed_status_ready"),
        (_status(schema_version=3), "unsupported_status_schema_version"),
    ],
)
def test_command_terminal_and_successful_malformed_status_fail_closed(
    tmp_path: Path, result: ProcessResult, reason: str
) -> None:
    config = _config(tmp_path)
    runner = FakeRunner([result])
    clock = FakeClock()

    with pytest.raises(GateError, match=f"^{reason}$"):
        _run(config, runner, clock)

    artifact = json.loads(config.resolved_output().read_text())
    assert artifact["state"] == "failed"
    assert artifact["reason"] == reason
    assert len(runner.calls) == 1


def test_rc1_unavailability_is_bounded_and_never_persists_output(tmp_path: Path) -> None:
    config = _config(tmp_path, max_status_unavailable=2)
    runner = FakeRunner(
        [
            ProcessResult(1, "", "stderr-with-unit-test-secret"),
            ProcessResult(1, "null"),
            ProcessResult(1, "not-json-with-unit-test-secret"),
        ]
    )
    clock = FakeClock()

    with pytest.raises(GateError, match="^status_unavailable_limit_exceeded$"):
        _run(config, runner, clock)

    persisted = config.resolved_output().read_text()
    artifact = json.loads(persisted)
    assert artifact["state"] == "failed"
    assert artifact["reason"] == "status_unavailable_limit_exceeded"
    assert artifact["consecutive_status_unavailable"] == 3
    assert artifact["status_unavailable_reason"] == "malformed_status_json"
    assert artifact["consecutive_ready_polls"] == 0
    assert "unit-test-secret" not in persisted
    assert len(runner.calls) == 3


def test_valid_status_resets_unavailability_budget_and_readiness_streak(
    tmp_path: Path,
) -> None:
    config = _config(
        tmp_path,
        consecutive_polls=2,
        max_status_unavailable=1,
    )
    runner = FakeRunner(
        [
            ProcessResult(1, ""),
            _status(phase="booting", ready=0, pending=24, coord_ticks=10),
            _status(coord_ticks=11),
            ProcessResult(1, "null"),
            _status(coord_ticks=12),
            _status(coord_ticks=13),
            _probe(),
            _status(coord_ticks=14),
        ]
    )
    clock = FakeClock()

    artifact = _run(config, runner, clock)

    assert artifact["state"] == "passed"
    assert artifact["polls"] == 6
    assert artifact["consecutive_status_unavailable"] == 0
    assert artifact["status_unavailable_reason"] is None
    assert artifact["consecutive_ready_polls"] == 2


def test_valid_degraded_and_draining_snapshots_only_reset_streak(tmp_path: Path) -> None:
    config = _config(tmp_path)
    degraded = _status(ready=20, pending=0, running_not_ready=0, coord_ticks=11)
    draining = _status(phase="draining", coord_ticks=13)
    runner = FakeRunner(
        [
            _status(coord_ticks=10),
            degraded,
            _status(coord_ticks=12),
            draining,
            _status(coord_ticks=14),
            _status(coord_ticks=15),
            _status(coord_ticks=16),
            _probe(),
            _status(coord_ticks=17),
        ]
    )
    clock = FakeClock()

    artifact = _run(config, runner, clock)

    assert artifact["state"] == "passed"
    assert artifact["polls"] == 7
    assert artifact["consecutive_ready_polls"] == 3


def test_timeout_is_persisted_when_proxy_info_never_becomes_readable(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, wait_timeout=2.0)
    assert config.proxy_info is not None
    config.proxy_info.unlink()
    runner = FakeRunner([_status(coord_ticks=10), _status(coord_ticks=11), _status(coord_ticks=12)])
    clock = FakeClock()

    with pytest.raises(GateError, match="^wait_timeout$"):
        _run(config, runner, clock)

    artifact = json.loads(config.resolved_output().read_text())
    assert artifact["state"] == "failed"
    assert artifact["reason"] == "wait_timeout"
    assert artifact["proxy_info_readable"] is False
    assert artifact["endpoint"] is None
    assert len(runner.calls) == 2


def test_probe_failure_is_redacted_and_never_retried(tmp_path: Path) -> None:
    config = _config(tmp_path, consecutive_polls=1)
    runner = FakeRunner([_status(), _probe(ok=False)])
    clock = FakeClock()

    with pytest.raises(GateError, match="^probe_failed$"):
        _run(config, runner, clock)

    persisted = config.resolved_output().read_text()
    artifact = json.loads(persisted)
    assert artifact["state"] == "failed"
    assert artifact["reason"] == "probe_failed"
    assert artifact["probe"]["ok"] is False
    assert artifact["probe"]["failure"] == "Bearer <redacted>"
    assert "unit-test-secret" not in persisted
    assert "http://proxy-info-url:8100" not in persisted
    assert len(runner.calls) == 2


def test_probe_endpoint_digest_must_match_bound_proxy_info(tmp_path: Path) -> None:
    config = _config(tmp_path, consecutive_polls=1)
    runner = FakeRunner([_status(), _probe(endpoint_authority_sha256="0" * 64)])
    clock = FakeClock()

    with pytest.raises(GateError, match="^probe_endpoint_mismatch$"):
        _run(config, runner, clock)

    artifact = json.loads(config.resolved_output().read_text())
    assert artifact["state"] == "failed"
    assert artifact["reason"] == "probe_endpoint_mismatch"


def test_proxy_info_is_rehashed_after_probe(tmp_path: Path) -> None:
    config = _config(tmp_path, consecutive_polls=1)
    assert config.proxy_info is not None

    class MutatingRunner(FakeRunner):
        def __call__(self, argv: Sequence[str], timeout: float) -> ProcessResult:
            result = super().__call__(argv, timeout)
            if "--proxy-info-sha256" in argv:
                payload = json.loads(config.proxy_info.read_text())
                payload["api_key"] = "rotated-unit-test-secret"
                config.proxy_info.write_text(json.dumps(payload))
            return result

    runner = MutatingRunner([_status(), _probe()])
    clock = FakeClock()

    with pytest.raises(GateError, match="^proxy_info_changed$"):
        _run(config, runner, clock)

    persisted = config.resolved_output().read_text()
    artifact = json.loads(persisted)
    assert artifact["state"] == "failed"
    assert artifact["reason"] == "proxy_info_changed"
    assert "unit-test-secret" not in persisted


def test_spec_is_rehashed_after_probe(tmp_path: Path) -> None:
    config = _config(tmp_path, consecutive_polls=1)
    assert config.spec is not None

    class MutatingRunner(FakeRunner):
        def __call__(self, argv: Sequence[str], timeout: float) -> ProcessResult:
            result = super().__call__(argv, timeout)
            if "--proxy-info-sha256" in argv:
                config.spec.write_text("mutated-during-probe: true\n")
            return result

    runner = MutatingRunner([_status(), _probe()])
    clock = FakeClock()

    with pytest.raises(GateError, match="^spec_sha256_mismatch$"):
        _run(config, runner, clock)

    artifact = json.loads(config.resolved_output().read_text())
    assert artifact["state"] == "failed"
    assert artifact["reason"] == "spec_sha256_mismatch"
    assert artifact["observed_spec_sha256"] == hashlib.sha256(config.spec.read_bytes()).hexdigest()


def test_spec_is_rehashed_immediately_before_probe(tmp_path: Path) -> None:
    config = _config(tmp_path, consecutive_polls=1)
    assert config.spec is not None

    class MutatingRunner(FakeRunner):
        def __call__(self, argv: Sequence[str], timeout: float) -> ProcessResult:
            result = super().__call__(argv, timeout)
            config.spec.write_text("mutated: true\n")
            return result

    runner = MutatingRunner([_status()])
    clock = FakeClock()

    with pytest.raises(GateError, match="^spec_sha256_mismatch$"):
        _run(config, runner, clock)

    artifact = json.loads(config.resolved_output().read_text())
    assert artifact["state"] == "failed"
    assert artifact["reason"] == "spec_sha256_mismatch"
    assert artifact["observed_spec_sha256"] == hashlib.sha256(config.spec.read_bytes()).hexdigest()
    assert len(runner.calls) == 1


def test_spec_is_rehashed_before_every_status_poll(tmp_path: Path) -> None:
    config = _config(tmp_path)
    assert config.spec is not None
    runner = FakeRunner([_status(phase="booting", ready=0, pending=24)])
    clock = FakeClock()

    def mutate_spec_and_advance(seconds: float) -> None:
        config.spec.write_text("mutated-between-polls: true\n")
        clock.sleep(seconds)

    with pytest.raises(GateError, match="^spec_sha256_mismatch$"):
        run_gate(
            config,
            runner=runner,
            monotonic=clock.monotonic,
            sleeper=mutate_spec_and_advance,
            emit=lambda _message: None,
        )

    artifact = json.loads(config.resolved_output().read_text())
    assert artifact["observed_spec_sha256"] == hashlib.sha256(config.spec.read_bytes()).hexdigest()
    assert len(runner.calls) == 1


def test_all_proxy_environment_variables_are_removed_from_children() -> None:
    child = _child_environment(
        {
            "PATH": "/bin",
            "HTTP_PROXY": "http://forward",
            "https_proxy": "http://forward",
            "ALL_PROXY": "socks5://forward",
            "no_proxy": "localhost",
            "CUSTOM_PROXY": "must-not-leak",
        }
    )

    assert child == {"PATH": "/bin"}


def test_status_command_uses_gate_interpreter_and_pins_serve_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path)
    inherited_pythonpath = os.pathsep.join(
        (
            "/gate/workflow",
            "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64",
        )
    )
    monkeypatch.setenv("PYTHONPATH", inherited_pythonpath)

    assert _status_command(config) == [
        "/usr/bin/env",
        "PATH=/usr/bin:/bin",
        f"PYTHONPATH={config.serve_sh.resolve().parent / 'src'}{os.pathsep}{inherited_pythonpath}",
        sys.executable,
        "-m",
        "serve_api_v2.cli.status",
        config.deployment,
        "--json",
    ]


def test_sbatch_wrapper_is_cpu_only_and_forwards_safe_tunables(tmp_path: Path) -> None:
    wrapper = Path(__file__).parents[1] / "wait_for_inference_routes.sbatch"
    wrapper_text = wrapper.read_text()
    for directive in (
        "#SBATCH --partition=cpu_x86",
        "#SBATCH --qos=cpu_x86_lowest",
        "#SBATCH --account=ram",
        "#SBATCH --time=7-00:00:00",
        "#SBATCH --cpus-per-task=1",
        "#SBATCH --mem=2G",
        "#SBATCH --no-requeue",
    ):
        assert directive in wrapper_text
    assert "#SBATCH --gres" not in wrapper_text
    assert "#SBATCH --gpus" not in wrapper_text
    assert (
        "x86_site=${PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64}"
    ) in wrapper_text

    workflow = tmp_path / "user/tianhaowu/terminal_bench_vmvm"
    workflow.mkdir(parents=True)
    x86_site = tmp_path / "python_x86_64"
    x86_site.mkdir()
    (x86_site / "gate_x86_dependency.py").write_text("MARKER = 'x86-site'\n")
    inherited_site = tmp_path / "inherited_pythonpath"
    inherited_site.mkdir()
    capture = tmp_path / "capture.json"
    dummy_waiter = workflow / "wait_for_inference_routes.py"
    dummy_waiter.write_text(
        "import gate_x86_dependency, json, os, pathlib, sys\n"
        "pathlib.Path(os.environ['CAPTURE']).write_text(json.dumps({"
        "'argv': sys.argv[1:], "
        "'dependency_marker': gate_x86_dependency.MARKER, "
        "'pythonpath': os.environ['PYTHONPATH'], "
        "'proxy_names': sorted(k for k in os.environ if k.lower().endswith('_proxy'))"
        "}))\n"
    )
    env = {
        **os.environ,
        "PROJECT_DIR": str(tmp_path),
        "DEPLOYMENT_ID": "deployment-1",
        "EXPECTED_SPEC_SHA256": "a" * 64,
        "GATE_OUTPUT": str(tmp_path / "gate.json"),
        "EXPECTED_ROUTES": "7",
        "CONSECUTIVE_POLLS": "5",
        "MAX_STATUS_UNAVAILABLE": "4",
        "PROBE_REQUESTS": "56",
        "PROBE_CONCURRENCY": "7",
        "CAPTURE": str(capture),
        "PYTHON_SITE_X86_64": str(x86_site),
        "PYTHONPATH": str(inherited_site),
        "HTTP_PROXY": "http://forward",
        "https_proxy": "http://forward",
        "CUSTOM_PROXY": "must-not-leak",
    }

    completed = subprocess.run(
        ["bash", str(wrapper)],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    invocation = json.loads(capture.read_text())
    assert invocation["proxy_names"] == []
    assert invocation["dependency_marker"] == "x86-site"
    assert invocation["pythonpath"].split(os.pathsep) == [
        str(workflow),
        str(x86_site),
        str(inherited_site),
    ]
    argv = invocation["argv"]
    assert argv[0] == "deployment-1"
    assert argv[argv.index("--expected-spec-sha256") + 1] == "a" * 64
    assert argv[argv.index("--expected-routes") + 1] == "7"
    assert argv[argv.index("--consecutive-polls") + 1] == "5"
    assert argv[argv.index("--max-status-unavailable") + 1] == "4"
    assert argv[argv.index("--probe-requests") + 1] == "56"
    assert argv[argv.index("--probe-concurrency") + 1] == "7"
    assert "--allow-unverified-affinity" not in argv
    assert "--skip-health" not in argv
