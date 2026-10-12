from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import probe_sandoq_firecracker_small_capacity as probe
import pytest


class _NotFound(Exception):
    pass


class _ConnectionFailure(Exception):
    pass


class _SessionFailure(Exception):
    pass


class _Client:
    def __init__(
        self,
        *,
        failed_slots: set[int] | None = None,
        unready_slots: set[int] | None = None,
        never_missing: bool = False,
        expected_concurrency: int = 24,
    ) -> None:
        self.http = SimpleNamespace(proxy_url="https://proxy.invalid", ssl_context=object())
        self.failed_slots = failed_slots or set()
        self.unready_slots = unready_slots or set()
        self.never_missing = never_missing
        self.expected_concurrency = expected_concurrency
        self.started = 0
        self.live: set[str] = set()
        self.deleted: set[str] = set()
        self.max_live = 0
        self.create_release = asyncio.Event()
        self.closed = False

    async def create_session(
        self,
        *,
        environment_name: str,
        lease_duration: str,
        request_id: str,
        ready_timeout_seconds: float,
    ) -> object:
        assert environment_name == probe.ENVIRONMENT
        assert lease_duration == probe.LEASE_DURATION
        assert ready_timeout_seconds == probe.CREATE_DEADLINE_SECONDS
        slot = int(request_id.removeprefix("request-"))
        self.started += 1
        if self.started == self.expected_concurrency:
            self.create_release.set()
        await self.create_release.wait()
        if slot in self.failed_slots:
            raise _SessionFailure("private provider detail")
        session_id = f"private-session-{slot}"
        self.live.add(session_id)
        self.max_live = max(self.max_live, len(self.live))
        return SimpleNamespace(session_id=session_id, status=None)

    async def get_session(self, session_id: str) -> object:
        if session_id in self.deleted and not self.never_missing:
            raise _NotFound
        if session_id not in self.live and session_id not in self.deleted:
            raise _NotFound
        slot = int(session_id.removeprefix("private-session-"))
        status = SimpleNamespace(value="provisioning") if slot in self.unready_slots else None
        return SimpleNamespace(session_id=session_id, status=status)

    async def delete_session(self, session_id: str) -> None:
        self.live.discard(session_id)
        self.deleted.add(session_id)

    async def close(self) -> None:
        self.closed = True


class _CancellationClient(_Client):
    def __init__(self, expected_concurrency: int = 24) -> None:
        super().__init__(expected_concurrency=expected_concurrency)
        self.blocked = 0
        self.all_blocked = asyncio.Event()

    async def create_session(
        self,
        *,
        environment_name: str,
        lease_duration: str,
        request_id: str,
        ready_timeout_seconds: float,
    ) -> object:
        slot = int(request_id.removeprefix("request-"))
        if slot < 3:
            session_id = f"private-session-{slot}"
            self.live.add(session_id)
            return SimpleNamespace(session_id=session_id, status=None)
        self.blocked += 1
        if self.blocked == self.expected_concurrency - 3:
            self.all_blocked.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


def _environment() -> dict[str, str]:
    return {"SLURM_JOB_ID": "1594000", "USER": "tester"}


def _bindings(client: _Client) -> probe.SdkBindings:
    return probe.SdkBindings(
        client_factory=lambda _base_url, _owner: client,
        not_found_exception=_NotFound,
        connection_exception=_ConnectionFailure,
        session_exception=_SessionFailure,
        version="fixture-sdk",
    )


def _profile(tmp_path: Path) -> probe.ProviderProfile:
    path = (tmp_path / "profile.json").resolve()
    path.write_text(json.dumps(probe.EXPECTED_PROFILE, sort_keys=True))
    return probe._load_profile(path)


def _request_ids() -> object:
    value = 0

    def next_id() -> str:
        nonlocal value
        result = f"request-{value}"
        value += 1
        return result

    return next_id


@pytest.mark.parametrize("concurrency", probe.ALLOWED_CONCURRENCIES)
def test_capacity_soak_holds_all_ready_sessions_then_verifies_every_404(
    tmp_path: Path,
    concurrency: int,
) -> None:
    client = _Client(expected_concurrency=concurrency)

    result, passed = asyncio.run(
        probe.run_soak(
            profile=_profile(tmp_path),
            concurrency=concurrency,
            environment=_environment(),
            bindings=_bindings(client),
            request_id_factory=_request_ids(),
        )
    )

    assert passed is True
    assert result["state"] == "passed"
    assert result["kind"] == f"sandoq-firecracker-small-c{concurrency}-soak"
    assert result["requested_concurrency"] == concurrency
    assert result["create_attempts"] == concurrency
    assert result["sessions_returned"] == concurrency
    assert result["simultaneous_ready_verified"] == concurrency
    assert result["create_failure_counts"] == dict.fromkeys(probe.CREATE_FAILURE_KEYS, 0)
    assert result["delete_attempts"] == concurrency
    assert result["typed_404_verified"] == concurrency
    assert result["cleanup_failures"] == 0
    assert result["client_close_verified"] is True
    assert client.started == concurrency
    assert client.max_live == concurrency
    assert len(client.deleted) == concurrency
    assert client.live == set()
    assert client.closed is True
    serialized = json.dumps(result, sort_keys=True)
    assert "private-session" not in serialized
    assert "request-" not in serialized


def test_partial_create_failure_still_deletes_every_returned_session(tmp_path: Path) -> None:
    client = _Client(failed_slots={7})

    result, passed = asyncio.run(
        probe.run_soak(
            profile=_profile(tmp_path),
            concurrency=24,
            environment=_environment(),
            bindings=_bindings(client),
            request_id_factory=_request_ids(),
        )
    )

    assert passed is False
    assert result["state"] == "unavailable"
    assert result["sessions_returned"] == 23
    assert result["create_failure_counts"]["session_failure"] == 1
    assert result["delete_attempts"] == 23
    assert result["typed_404_verified"] == 23
    assert len(client.deleted) == 23
    assert client.live == set()
    assert client.closed is True
    assert "private provider detail" not in json.dumps(result)


def test_unready_get_or_missing_404_fails_closed_and_still_cleans(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client(unready_slots={4}, never_missing=True)
    monkeypatch.setattr(probe, "MISSING_VERIFY_DEADLINE_SECONDS", 0.001)
    monkeypatch.setattr(probe, "VERIFY_POLL_SECONDS", 0.0)

    result, passed = asyncio.run(
        probe.run_soak(
            profile=_profile(tmp_path),
            concurrency=24,
            environment=_environment(),
            bindings=_bindings(client),
            request_id_factory=_request_ids(),
        )
    )

    assert passed is False
    assert result["simultaneous_ready_verified"] == 23
    assert result["delete_attempts"] == 24
    assert result["typed_404_verified"] == 0
    assert result["cleanup_failures"] == 24
    assert len(client.deleted) == 24
    assert client.closed is True


def test_cancellation_deletes_every_returned_session_before_propagating(tmp_path: Path) -> None:
    client = _CancellationClient()

    async def cancel_soak() -> None:
        task = asyncio.create_task(
            probe.run_soak(
                profile=_profile(tmp_path),
                concurrency=24,
                environment=_environment(),
                bindings=_bindings(client),
                request_id_factory=_request_ids(),
            )
        )
        await client.all_blocked.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel_soak())
    assert client.deleted == {
        "private-session-0",
        "private-session-1",
        "private-session-2",
    }
    assert client.live == set()
    assert client.closed is True


def test_profile_is_exact_and_receipt_is_owner_only(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    assert profile.environment == probe.ENVIRONMENT
    assert len(profile.sha256) == 64

    bad = (tmp_path / "bad.json").resolve()
    bad.write_text(json.dumps({**probe.EXPECTED_PROFILE, "environment": "wrong"}))
    with pytest.raises(probe.SoakError, match="^profile_invalid$"):
        probe._load_profile(bad)

    output_dir = tmp_path / "output"
    output_dir.mkdir(mode=0o700)
    output = (output_dir / "receipt.json").resolve()
    probe._publish_private(output, {"kind": probe._kind_for_concurrency(24), "state": "fixture"})
    assert output.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {"SLURM_JOB_ID": "1594000", "USER": "tester", "HTTPS_PROXY": "private"},
        {"SLURM_JOB_ID": "1594000", "USER": "tester", "OCI_RUNNER_TOKEN": "private"},
    ],
)
def test_probe_rejects_non_slurm_proxy_or_bearer_environment(environment: dict[str, str]) -> None:
    with pytest.raises(probe.SoakError, match="^probe_environment_invalid$"):
        probe._validate_environment(environment)


def test_deadlines_fit_the_fifteen_minute_launcher() -> None:
    assert probe.HARD_WALL_SECONDS < 15 * 60 - 180
    assert probe.LEASE_DURATION == "10m"


def test_cli_and_runtime_accept_only_explicit_c24_or_c64(tmp_path: Path) -> None:
    output = tmp_path / "receipt.json"
    profile = tmp_path / "profile.json"
    for concurrency in probe.ALLOWED_CONCURRENCIES:
        args = probe._parser().parse_args(
            ["--concurrency", str(concurrency), "--profile", str(profile), "--output", str(output)]
        )
        assert args.concurrency == concurrency
        assert probe._kind_for_concurrency(concurrency) == f"sandoq-firecracker-small-c{concurrency}-soak"
    for invalid in (0, 23, 25, 63, 65, True):
        with pytest.raises(probe.SoakError, match="^concurrency_invalid$"):
            probe._kind_for_concurrency(invalid)


def test_launcher_pins_source_profile_sdk_and_private_bounded_execution() -> None:
    launcher = Path(probe.__file__).with_name("run_sandoq_firecracker_small_capacity_probe.sbatch").read_text()

    assert "#SBATCH --time=00:15:00" in launcher
    assert "#SBATCH --signal=B:TERM@180" in launcher
    assert "SANDOQ_SMALL_CAPACITY_CONCURRENCY" in launcher
    assert '[[ "$concurrency" == 24 || "$concurrency" == 64 ]]' in launcher
    assert "SANDOQ_SMALL_CAPACITY_EXPECTED_REVISION" in launcher
    assert "SANDOQ_SMALL_CAPACITY_PROBE_SHA256" in launcher
    assert "SANDOQ_SMALL_CAPACITY_LAUNCHER_SHA256" in launcher
    assert "SANDOQ_SMALL_CAPACITY_PROFILE_SHA256" in launcher
    assert "kimi_sandoq_firecracker_small_host.json" in launcher
    assert "sandoq_x86_64_sdk1_82068" in launcher
    assert "setsid env" in launcher
    assert '--concurrency "$concurrency"' in launcher
    assert "sandoq-firecracker-small-c${concurrency}-soak-20260927" in launcher
    assert "terminate_group" in launcher
    assert 'chmod 600 -- "$receipt"' not in launcher
    assert '"$(stat -c \'%u:%a\' -- "$receipt")" == "$(id -u):600"' in launcher
    assert "OCI_RUNNER_TOKEN" in launcher
    assert "SANDOQ_AUTH_TOKEN" in launcher
    assert "task_file" not in launcher
    assert "task_id" not in launcher
    assert "prompt" not in launcher.lower()
