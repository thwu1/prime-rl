import asyncio
import importlib.util
import json
import signal
from pathlib import Path
from types import SimpleNamespace

import pytest

RUN_ORACLE = Path(__file__).parents[1] / "run_oracle.py"
SPEC = importlib.util.spec_from_file_location("terminal_bench_vmvm_run_oracle", RUN_ORACLE)
assert SPEC is not None and SPEC.loader is not None
run_oracle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(run_oracle)


def test_oracle_network_semantics_are_immutable_and_resumable(tmp_path: Path) -> None:
    expected = {
        "schema_version": 1,
        "trusted_reference_solution": "public",
        "verifier": "declared",
    }

    assert run_oracle._bind_oracle_network_semantics(tmp_path, "public") == expected
    assert json.loads((tmp_path / "oracle_network_semantics.json").read_text()) == expected
    assert run_oracle._bind_oracle_network_semantics(tmp_path, "public") == expected

    with pytest.raises(SystemExit, match="semantics mismatch"):
        run_oracle._bind_oracle_network_semantics(tmp_path, "declared")


def test_oracle_network_semantics_reject_unlabeled_results(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "legacy.json").write_text("{}\n")

    with pytest.raises(SystemExit, match="no immutable network-semantics label"):
        run_oracle._bind_oracle_network_semantics(tmp_path, "declared")


def test_oracle_summary_contains_network_semantics() -> None:
    semantics = run_oracle._oracle_network_semantics("public")
    summary = run_oracle._summary(
        [{"valid": True, "reason": "valid"}, {"valid": False, "reason": "invalid"}],
        2,
        semantics,
    )

    assert summary["passed"] == 1
    assert summary["pass_rate"] == 0.5
    assert summary["oracle_network_semantics"] == semantics


def test_oracle_attempt_cleans_taskset_before_runtime_stop_on_cancellation(monkeypatch) -> None:
    events: list[str] = []
    setup_started = asyncio.Event()

    class Runtime:
        descriptor = "runtime"

        async def start(self) -> None:
            events.append("runtime-start")

        async def stop(self) -> None:
            events.append("runtime-stop")

    class Taskset:
        async def setup_oracle(self, task, runtime) -> None:
            events.append("taskset-setup")
            setup_started.set()
            await asyncio.Event().wait()

        async def validate(self, task, runtime) -> bool:
            raise AssertionError("cancelled setup must not reach validation")

        async def cleanup(self, task, trace, runtime) -> None:
            assert trace is None
            events.append("taskset-cleanup")

    runtime = Runtime()
    monkeypatch.setattr(run_oracle, "resolve_runtime_config", lambda config, task: config)
    monkeypatch.setattr(run_oracle, "make_runtime", lambda config, name: runtime)

    async def exercise() -> None:
        attempt = asyncio.create_task(
            run_oracle._attempt(
                Taskset(),
                SimpleNamespace(idx=0, name="test"),
                SimpleNamespace(),
                setup_timeout=30,
                validate_timeout=30,
                attempt=1,
            )
        )
        await setup_started.wait()
        attempt.cancel()
        with pytest.raises(asyncio.CancelledError):
            await attempt

    asyncio.run(exercise())

    assert events[-2:] == ["taskset-cleanup", "runtime-stop"]


def test_oracle_main_translates_sigterm_to_graceful_interrupt(monkeypatch) -> None:
    installed: dict[int, object] = {}

    def install_signal(number: int, handler: object) -> None:
        installed[number] = handler

    def run(coroutine) -> int:
        coroutine.close()
        return 0

    monkeypatch.setattr(run_oracle, "_parse_args", lambda: SimpleNamespace(log_level="INFO"))
    monkeypatch.setattr(run_oracle.signal, "signal", install_signal)
    monkeypatch.setattr(run_oracle.asyncio, "run", run)

    with pytest.raises(SystemExit) as exit_info:
        run_oracle.main()

    assert exit_info.value.code == 0
    assert signal.SIGTERM in installed
