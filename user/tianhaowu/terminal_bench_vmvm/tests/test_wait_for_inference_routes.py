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
from wait_for_inference_routes import (
    GateConfig,
    GateError,
    ProcessResult,
    _child_environment,
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
        return self.results.pop(0)


def _status(
    *,
    phase: str = "serving",
    desired: Any = 24,
    ready: Any = 24,
    running_not_ready: Any = 0,
    pending: Any = 0,
    deployment: str = "test-deployment",
) -> ProcessResult:
    payload = {
        "schema_version": 4,
        "deployment_id": deployment,
        "phase": phase,
        "terminal_reason": None,
        "coord": {"ticks_completed": 10},
        "endpoints_summary": {
            "desired": desired,
            "ready": ready,
            "running_not_ready": running_not_ready,
            "pending": pending,
        },
        # These fields must never be copied into the artifact.
        "proxy": {"url": "http://private-proxy:8100", "api_key": "status-secret"},
        "spec": {"future_secret": "do-not-copy"},
    }
    return ProcessResult(0 if phase == "serving" else 1, json.dumps(payload))


def _probe(*, ok: bool = True, returncode: int | None = None) -> ProcessResult:
    payload = {
        "ok": ok,
        "proxy_base_url": "http://proxy-info-url:8100",
        "coverage": {"ok": ok, "discovered_routes": 24},
        "requests": {"ok": ok, "failed": 0 if ok else 1},
        "future_api_key": "not-a-known-key-name",
        "failure": "Bearer unit-test-secret" if not ok else None,
    }
    return ProcessResult(returncode if returncode is not None else (0 if ok else 1), json.dumps(payload))


def _config(tmp_path: Path, **overrides: Any) -> GateConfig:
    serve_sh = tmp_path / "serve.sh"
    probe_script = tmp_path / "probe.py"
    serve_sh.touch()
    probe_script.touch()
    spec = tmp_path / "spec.yaml"
    spec.write_text("immutable: true\n")
    proxy_info = tmp_path / "proxy_info.json"
    proxy_info.write_text(
        json.dumps(
            {
                "url": "http://proxy-info-url:8100",
                "api_key": "unit-test-secret",
                "extras": {"sticky": True},
            }
        )
    )
    values: dict[str, Any] = {
        "deployment": "test-deployment",
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
    runner = FakeRunner([_status(), _status(), _status(), _probe()])
    clock = FakeClock()

    artifact = _run(config, runner, clock)

    assert artifact["state"] == "passed"
    assert artifact["polls"] == 3
    assert artifact["consecutive_ready_polls"] == 3
    assert artifact["proxy_info_readable"] is True
    assert artifact["observed_spec_sha256"] == config.expected_spec_sha256
    persisted = config.resolved_output().read_text()
    assert json.loads(persisted) == artifact
    assert "unit-test-secret" not in persisted
    assert "status-secret" not in persisted
    assert "do-not-copy" not in persisted
    assert "http://proxy-info-url:8100" not in persisted
    assert artifact["probe"]["proxy_base_url"] == "<redacted>"
    assert artifact["probe"]["future_api_key"] == "<redacted>"
    assert config.resolved_output().stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob(".gate.json.*.tmp"))

    status_argv = runner.calls[0][0]
    assert status_argv == [
        str(config.serve_sh),
        "status",
        config.deployment,
        "--json",
    ]
    probe_argv = runner.calls[-1][0]
    assert probe_argv[:2] == [sys.executable, str(config.probe_script)]
    assert probe_argv[probe_argv.index("--expected-routes") + 1] == "24"
    assert probe_argv[probe_argv.index("--requests") + 1] == "192"
    assert probe_argv[probe_argv.index("--concurrency") + 1] == "24"
    assert "--require-reasoning" in probe_argv
    assert "--allow-unverified-affinity" not in probe_argv
    assert "--skip-health" not in probe_argv
    assert all("logprob" not in argument for argument in probe_argv)
    assert "return_token_ids" not in probe_argv


def test_nonready_poll_resets_consecutive_streak(tmp_path: Path) -> None:
    config = _config(tmp_path)
    booting = _status(
        phase="booting",
        ready=23,
        running_not_ready=1,
    )
    runner = FakeRunner([_status(), booting, _status(), _status(), _status(), _probe()])
    clock = FakeClock()

    artifact = _run(config, runner, clock)

    assert artifact["state"] == "passed"
    assert artifact["polls"] == 5
    assert artifact["consecutive_ready_polls"] == 3


@pytest.mark.parametrize(
    ("result", "reason"),
    [
        (ProcessResult(2, _status().stdout), "status_command_failed"),
        (ProcessResult(0, "not-json"), "malformed_status_json"),
        (_status(phase="failed"), "terminal_deployment"),
        (_status(phase="FAILED"), "terminal_deployment"),
        (_status(ready=True, pending=23), "malformed_status_ready"),
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
            _status(phase="booting", ready=0, pending=24),
            _status(),
            ProcessResult(1, "null"),
            _status(),
            _status(),
            _probe(),
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
    degraded = _status(ready=20, pending=0, running_not_ready=0)
    draining = _status(phase="draining")
    runner = FakeRunner(
        [
            _status(),
            degraded,
            _status(),
            draining,
            _status(),
            _status(),
            _status(),
            _probe(),
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
    runner = FakeRunner([_status(), _status(), _status()])
    clock = FakeClock()

    with pytest.raises(GateError, match="^wait_timeout$"):
        _run(config, runner, clock)

    artifact = json.loads(config.resolved_output().read_text())
    assert artifact["state"] == "failed"
    assert artifact["reason"] == "wait_timeout"
    assert artifact["proxy_info_readable"] is False
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

    workflow = tmp_path / "user/tianhaowu/terminal_bench_vmvm"
    workflow.mkdir(parents=True)
    capture = tmp_path / "capture.json"
    dummy_waiter = workflow / "wait_for_inference_routes.py"
    dummy_waiter.write_text(
        "import json, os, pathlib, sys\n"
        "pathlib.Path(os.environ['CAPTURE']).write_text(json.dumps({"
        "'argv': sys.argv[1:], "
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
