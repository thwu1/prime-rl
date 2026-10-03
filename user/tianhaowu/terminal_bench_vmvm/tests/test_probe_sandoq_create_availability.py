from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import probe_sandoq_create_availability as probe
import pytest


class _NotFound(Exception):
    pass


class _ConnectionFailure(Exception):
    def __init__(self, private_message: str, *, response_received: bool = False) -> None:
        super().__init__(private_message)
        self.response_received = response_received


class _SessionFailure(Exception):
    def __init__(self, private_message: str, *, response_received: bool = True) -> None:
        super().__init__(private_message)
        self.response_received = response_received


class _Client:
    def __init__(self, *, failure: BaseException | None = None, typed_missing: bool = True) -> None:
        self.http = SimpleNamespace(proxy_url="https://proxy.invalid", ssl_context=object())
        self.failure = failure
        self.typed_missing = typed_missing
        self.create_arguments: dict[str, object] | None = None
        self.deleted: list[str] = []
        self.closed = False

    async def create_session(
        self,
        *,
        environment_name: str,
        lease_duration: str,
        request_id: str,
        ready_timeout_seconds: float,
    ) -> object:
        self.create_arguments = {
            "environment_name": environment_name,
            "lease_duration": lease_duration,
            "request_id": request_id,
            "ready_timeout_seconds": ready_timeout_seconds,
        }
        if self.failure is not None:
            raise self.failure
        return SimpleNamespace(session_id="private-session-id")

    async def delete_session(self, session_id: str) -> None:
        self.deleted.append(session_id)

    async def get_session(self, _session_id: str) -> object:
        if self.typed_missing:
            raise _NotFound
        return object()

    async def close(self) -> None:
        self.closed = True


class _OldClient(_Client):
    async def create_session(
        self,
        *,
        environment_name: str,
        lease_duration: str,
        request_id: str,
    ) -> object:
        self.create_arguments = {
            "environment_name": environment_name,
            "lease_duration": lease_duration,
            "request_id": request_id,
        }
        return SimpleNamespace(session_id="private-old-session-id")


class _BlockingClient(_Client):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()

    async def create_session(
        self,
        *,
        environment_name: str,
        lease_duration: str,
        request_id: str,
        ready_timeout_seconds: float,
    ) -> object:
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


def _environment() -> dict[str, str]:
    return {"SLURM_JOB_ID": "1590774", "USER": "tester", "SCENV": "fixture"}


def _bindings(client: _Client, version: str = "fixture-sdk") -> probe.SdkBindings:
    return probe.SdkBindings(
        client_factory=lambda _owner: client,
        not_found_exception=_NotFound,
        connection_exception=_ConnectionFailure,
        session_exception=_SessionFailure,
        version=version,
    )


def test_success_requires_typed_cleanup_and_emits_no_session_identity() -> None:
    client = _Client()

    result, passed = asyncio.run(
        probe.run_probe(
            environment=_environment(),
            bindings=_bindings(client),
            request_id_factory=lambda: "private-request-id",
            monotonic=iter((10.0, 11.25)).__next__,
        )
    )

    assert passed is True
    assert result == {
        "sdk_version": "fixture-sdk",
        "transport_mode": "proxy",
        "mtls_available": True,
        "create_state": "created",
        "response_received": True,
        "session_returned": True,
        "cleanup_verified": True,
        "elapsed_seconds": 1.25,
    }
    assert client.create_arguments == {
        "environment_name": probe.ENVIRONMENT,
        "lease_duration": "5m",
        "request_id": "private-request-id",
        "ready_timeout_seconds": probe.CREATE_DEADLINE_SECONDS,
    }
    assert client.deleted == ["private-session-id"]
    assert client.closed is True
    serialized = json.dumps(result, sort_keys=True)
    assert "private-session-id" not in serialized
    assert "private-request-id" not in serialized


def test_connection_failure_is_redacted_and_does_not_claim_cleanup() -> None:
    client = _Client(failure=_ConnectionFailure("private transport reset detail"))

    result, passed = asyncio.run(probe.run_probe(environment=_environment(), bindings=_bindings(client)))

    assert passed is False
    assert result["create_state"] == "connection_failure"
    assert result["response_received"] is False
    assert result["session_returned"] is False
    assert result["cleanup_verified"] is False
    assert client.deleted == []
    assert client.closed is True
    assert "private transport reset detail" not in json.dumps(result)


def test_unverified_cleanup_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _Client(typed_missing=False)
    monkeypatch.setattr(probe, "VERIFY_DEADLINE_SECONDS", 0.001)
    monkeypatch.setattr(probe, "VERIFY_POLL_SECONDS", 0.0)

    result, passed = asyncio.run(probe.run_probe(environment=_environment(), bindings=_bindings(client)))

    assert passed is False
    assert result["create_state"] == "created"
    assert result["session_returned"] is True
    assert result["cleanup_verified"] is False
    assert client.deleted == ["private-session-id"]
    assert client.closed is True


def test_old_sdk_signature_uses_identical_minimal_create_contract() -> None:
    client = _OldClient()

    result, passed = asyncio.run(
        probe.run_probe(
            environment=_environment(),
            bindings=_bindings(client, "old-fixture-sdk"),
            request_id_factory=lambda: "private-request-id",
        )
    )

    assert passed is True
    assert result["sdk_version"] == "old-fixture-sdk"
    assert client.create_arguments == {
        "environment_name": probe.ENVIRONMENT,
        "lease_duration": "5m",
        "request_id": "private-request-id",
    }
    assert client.deleted == ["private-old-session-id"]


@pytest.mark.parametrize("invalid", [{}, {"SLURM_JOB_ID": "1590774", "USER": "tester", "HTTPS_PROXY": "x"}])
def test_probe_requires_real_proxy_clean_slurm_environment(invalid: dict[str, str]) -> None:
    with pytest.raises(probe.ProbeEnvironmentError, match="^probe_environment_invalid$"):
        asyncio.run(probe.run_probe(environment=invalid, bindings=_bindings(_Client())))


def test_cli_prints_one_sanitized_record(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    async def fail(**_kwargs: object) -> tuple[dict[str, object], bool]:
        raise RuntimeError("private provider failure")

    monkeypatch.setattr(probe, "run_probe", fail)
    assert probe.main() == 2
    captured = capsys.readouterr()
    assert captured.err == ""
    record = json.loads(captured.out)
    assert set(record) == probe.RESULT_KEYS
    assert record["create_state"] == "probe_failure"
    assert "private provider failure" not in captured.out


def test_process_deadline_bounds_all_normal_phase_deadlines() -> None:
    assert probe.HARD_WALL_SECONDS > (
        probe.CREATE_DEADLINE_SECONDS
        + probe.DELETE_DEADLINE_SECONDS
        + probe.VERIFY_DEADLINE_SECONDS
        + probe.CLOSE_DEADLINE_SECONDS
    )
    assert probe.HARD_WALL_SECONDS < 15 * 60 - 180


def test_cancellation_still_closes_the_official_client() -> None:
    client = _BlockingClient()

    async def cancel_probe() -> None:
        task = asyncio.create_task(probe.run_probe(environment=_environment(), bindings=_bindings(client)))
        await client.started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel_probe())
    assert client.closed is True


def test_launcher_pins_source_sdk_and_private_bounded_execution() -> None:
    launcher = Path(probe.__file__).with_name("run_sandoq_create_availability_probe.sbatch").read_text()

    assert "#SBATCH --partition=cpu_x86" in launcher
    assert "#SBATCH --time=00:15:00" in launcher
    assert "#SBATCH --signal=B:TERM@180" in launcher
    assert "SANDOQ_CREATE_PROBE_EXPECTED_REVISION" in launcher
    assert "SANDOQ_CREATE_PROBE_SHA256" in launcher
    assert "SANDOQ_CREATE_PROBE_LAUNCHER_SHA256" in launcher
    assert "sandoq_x86_64_sdk1_82068" in launcher
    assert "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64" in launcher
    assert (
        'PYTHONPATH="$project_dir:$project_dir/environments/vmvm_tb_v2:'
        '$project_dir/extensions/sandoq:$sandoq_site:$x86_site"'
    ) in launcher
    assert "df69cadb16edc799fcb62ea4fc144ee5d5572fe58fcd3e2bd6d165c607e02962" in launcher
    assert "1.0.0.2026.9.23.82068.0+hg1a1d394e50c5" in launcher
    assert "setsid env" in launcher
    assert "terminate_group" in launcher
    assert 'kill -INT -- "-$pgid"' in launcher
    assert 'mkdir -m 700 -- "$output_dir"' in launcher
    assert 'chmod 600 -- "$receipt"' in launcher
    assert "SANDOQ_AUTH_TOKEN" in launcher
    assert "FIRECRACKER_KEY" in launcher
    assert "task_file" not in launcher
    assert "task_id" not in launcher
    assert "prompt" not in launcher.lower()
