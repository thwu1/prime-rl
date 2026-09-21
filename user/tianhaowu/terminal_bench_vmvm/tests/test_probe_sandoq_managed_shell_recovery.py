from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import probe_sandoq_managed_shell_recovery as probe
import pytest

WORKFLOW_DIR = Path(__file__).parents[1]
PROBE_LAUNCHER = (
    WORKFLOW_DIR
    / "configs/eval/servers/cpu-132-021_8103/run_sandoq_managed_shell_recovery_probe_cpu-132-021_8103.sbatch"
)


class _FakeClient:
    def __init__(self) -> None:
        self.info = SimpleNamespace(shell_id="shell-old")
        self.commands: list[str] = []
        self.deleted = False
        self.drained = False

    async def create(self, request: object, *, deadline: float) -> object:
        assert getattr(request, "cpu_cores") == 1
        assert getattr(request, "memory_gb") == 2
        assert getattr(request, "disk_size_gb") == 10
        assert deadline > 0
        return SimpleNamespace(id="assignment-1")

    async def wait_for_creation(self, sandbox_id: str) -> None:
        assert sandbox_id == "assignment-1"

    async def execute_command(self, sandbox_id: str, command: str, **kwargs: object) -> object:
        del sandbox_id, kwargs
        self.commands.append(command)
        if len(self.commands) == 2:
            self.info.shell_id = "shell-new"
        return SimpleNamespace(exit_code=0)

    async def _request_json(self, info: object, method: str, path: str, **kwargs: object) -> object:
        del info, kwargs
        assert method == "DELETE"
        assert path == "v1/shells/shell-old"
        return SimpleNamespace(status_code=204)

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": "redacted"}

    async def session_metadata(self, sandbox_id: str) -> dict[str, object]:
        assert sandbox_id == "assignment-1"
        return {"managed_shell_recovery_count": 1}

    async def poison_assignment(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("successful probe must not poison")

    async def delete(self, sandbox_id: str, timeout: int) -> dict[str, object]:
        assert sandbox_id == "assignment-1"
        assert timeout == 300
        self.deleted = True
        return {
            "nested_recycle_verified": True,
            "shell_deleted": True,
            "poisoned": False,
            "managed_shell_recovery_count": 1,
        }

    async def drain_pool(self) -> dict[str, object]:
        self.drained = True
        return {"drained": True, "failures": {}}


@pytest.fixture
def sealed_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SANDOQ_PROVIDER_CONTEXT_ACTIVE", "1")
    monkeypatch.setenv("SANDOQ_LEASE_PROFILE", "kimi-tb4-long")
    monkeypatch.setenv("OCI_RUNNER_LEASE_DURATION", "12h")
    monkeypatch.setenv("OCI_RUNNER_POOL_RENEW_INTERVAL", "5m")
    monkeypatch.setenv("OCI_RUNNER_MANAGED_SHELL_RECOVERY", "1")
    monkeypatch.setenv("OCI_RUNNER_POOL_SIZE", "1")


def test_forced_delete_probe_is_task_free_and_publishes_private_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sealed_context: None,
) -> None:
    del sealed_context
    tmp_path.chmod(0o700)
    client = _FakeClient()
    monkeypatch.setattr(probe.registry, "get", lambda _sandbox_id: client.info)

    receipt = asyncio.run(
        probe.run_probe(
            mode="forced-delete",
            image=probe.DEFAULT_IMAGE,
            idle_seconds=0,
            output=tmp_path / "managed-shell-recovery.json",
            client=client,
        )
    )

    assert receipt["state"] == "passed"
    assert receipt["managed_shell_recovery_count"] == 1
    assert receipt["state_preserved"] is True
    assert client.deleted is True
    assert client.drained is True
    output = tmp_path / "managed-shell-recovery.json"
    assert output.stat().st_mode & 0o777 == 0o600
    assert json.loads(output.read_bytes()) == receipt


def test_idle_endurance_requires_more_than_managed_shell_ttl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sealed_context: None,
) -> None:
    del sealed_context
    tmp_path.chmod(0o700)
    client = _FakeClient()
    monkeypatch.setattr(probe.registry, "get", lambda _sandbox_id: client.info)
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    asyncio.run(
        probe.run_probe(
            mode="idle-endurance",
            image=probe.DEFAULT_IMAGE,
            idle_seconds=3_900,
            output=tmp_path / "managed-shell-recovery.json",
            client=client,
            sleep=sleep,
        )
    )

    assert slept == [3_900.0]


def test_probe_fails_closed_on_unsealed_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sealed_context: None,
) -> None:
    del sealed_context
    tmp_path.chmod(0o700)
    monkeypatch.setenv("OCI_RUNNER_MANAGED_SHELL_RECOVERY", "0")

    with pytest.raises(probe.RecoveryProbeError, match="probe_provider_context_invalid"):
        asyncio.run(
            probe.run_probe(
                mode="forced-delete",
                image=probe.DEFAULT_IMAGE,
                idle_seconds=0,
                output=tmp_path / "managed-shell-recovery.json",
                client=_FakeClient(),
            )
        )


def test_cli_redacts_unexpected_failure(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    secret = "private-member-identifier"

    async def fail(**kwargs: object) -> dict[str, object]:
        del kwargs
        raise RuntimeError(secret)

    monkeypatch.setattr(probe, "run_probe", fail)
    result = probe.main(
        [
            "--mode",
            "forced-delete",
            "--output",
            "/tmp/managed-shell-recovery.json",
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert secret not in captured.err
    assert "managed_shell_recovery_probe_failed" in captured.err


def test_probe_launcher_seals_complete_pythonpath_before_provider_supervision() -> None:
    launcher = PROBE_LAUNCHER.read_text()
    export = (
        'export PYTHONPATH="$workflow_dir:$project_dir/environments/vmvm_tb_v2:'
        "$project_dir/deps/verifiers:$project_dir/deps/renderers:"
        "$project_dir/deps/pydantic-config/src:$project_dir/extensions/sandoq:"
        '$sandoq_site:$x86_site"'
    )

    assert launcher.count(export) == 1
    assert launcher.index(export) < launcher.index("if [[ ${SANDOQ_PROVIDER_CONTEXT_ACTIVE:-} != 1 ]]")
    assert '-- /usr/bin/bash -p "${BASH_SOURCE[0]}"' in launcher
