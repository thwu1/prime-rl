import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest
import terminal_bench_vmvm.offline_verifier_catalog_materializer as materializer
import terminal_bench_vmvm.sandoq_catalog_worker as worker


def _digest(payload: bytes | str) -> str:
    if isinstance(payload, str):
        payload = payload.encode()
    return hashlib.sha256(payload).hexdigest()


def _worker_record(runtime_sha256: str = "a" * 64) -> dict[str, object]:
    return {
        "executable_sha256": "b" * 64,
        "runtime_sha256": runtime_sha256,
        "materializer_code_sha256": "c" * 64,
        "cleanup_receipt_verifier_sha256": worker.cleanup_receipt_verifier_sha256(),
        "environment_sha256": "d" * 64,
        "recovery_scope_sha256": "e" * 64,
        "ecr_rotator_sha256": "f" * 64,
        "credential_rotation_sha256": "1" * 64,
    }


def _wheel(name: str = "root-pkg", version: str = "1.0.0") -> tuple[str, bytes]:
    filename = f"{name.replace('-', '_')}-{version}-py3-none-any.whl"
    buffer = worker.BytesIO()
    info = ZipInfo(f"{name.replace('-', '_')}-{version}.dist-info/METADATA")
    info.date_time = (1980, 1, 1, 0, 0, 0)
    info.compress_type = ZIP_DEFLATED
    with ZipFile(buffer, "w") as archive:
        archive.writestr(info, f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n")
    return filename, buffer.getvalue()


class FakeBackend:
    def __init__(self, *, start_error: BaseException | None = None) -> None:
        self.events: list[str] = []
        self.commands: list[str] = []
        self.started_images: list[str] = []
        self.start_error = start_error
        self.network = "none"
        self.downloads: dict[str, bytes] = {}
        self.inventory_result: dict[str, object] | None = None
        self.cleanup_started = asyncio.Event()
        self.cleanup_release: asyncio.Event | None = None

    async def anchor_status(self) -> dict[str, object]:
        self.events.append("anchor")
        return {"accepting": True, "draining": False, "clients": 1}

    async def anchor_heartbeat(self) -> dict[str, object]:
        self.events.append("anchor-heartbeat")
        return {"accepting": True, "draining": False, "clients": 1}

    async def recover(self, reason: str) -> dict[str, object]:
        del reason
        self.events.append("recover")
        return {"drained": True, "deleted": [], "failures": {}}

    async def start(self, image: str, request_sha256: str, *, network: str) -> worker.RemoteSession:
        del request_sha256
        self.events.append("start")
        self.started_images.append(image)
        self.network = network
        if self.start_error is not None:
            raise self.start_error
        task_network = "none" if network == "none" else "host"
        return worker.RemoteSession(
            client=object(),
            registry=object(),
            sandbox_id="private-session",
            runtime_name="private-runtime",
            outer_session_id="private-outer",
            metadata={"environment": "oci-runner-firecracker", "task_network": task_network},
        )

    async def upload(self, session: worker.RemoteSession, path: str, payload: bytes) -> None:
        del session
        self.events.append("upload")
        self.downloads[path] = payload

    async def download(self, session: worker.RemoteSession, path: str) -> bytes:
        del session
        self.events.append("download")
        return self.downloads[path]

    async def execute(
        self,
        session: worker.RemoteSession,
        command: str,
        *,
        timeout: int,
        environment: dict[str, str] | None = None,
    ) -> tuple[int, str, str]:
        del session, timeout, environment
        self.events.append("execute")
        self.commands.append(command)
        if "/sys/class/net" in command:
            return 0, '{"default_route":false,"interfaces":["lo"],"network":"none"}', ""
        if "pip_version" in command and "python_version" in command:
            return 0, '{"pip_version":"24.3.1","python_version":"3.12.8"}', ""
        if "inventory-probe.py" in command:
            assert self.inventory_result is not None
            return 0, worker._canonical(self.inventory_result).decode(), ""
        if "--report" in command:
            return 0, "", ""
        if " download " in f" {command} ":
            return 0, "", ""
        if "p.iterdir" in command:
            names = sorted(path.rsplit("/", 1)[-1] for path in self.downloads if path.endswith(".whl"))
            return 0, json.dumps(names, separators=(",", ":")), ""
        return 0, "", ""

    async def cleanup(
        self,
        session: worker.RemoteSession,
        reason: str,
        *,
        poison: bool,
    ) -> dict[str, object]:
        del session, reason, poison
        self.events.append("cleanup-start")
        self.cleanup_started.set()
        if self.cleanup_release is not None:
            await self.cleanup_release.wait()
        self.events.append("cleanup-complete")
        return {"ok": True}


@pytest.mark.asyncio
async def test_probe_uses_no_network_session_and_releases_before_return() -> None:
    backend = FakeBackend()
    marker = {"python_version": "3.12", "sys_platform": "linux"}
    tags = ["py3-none-any"]
    fingerprint = {
        "schema_version": 1,
        "implementation": "cpython",
        "python_full_version": "3.12.8",
        "abi": "cpython-312-x86_64-linux-gnu",
        "platform": "linux-x86_64",
        "machine": "x86_64",
        "libc": "glibc-2.36",
        "pip_version": "24.3.1",
        "marker_environment_sha256": _digest(worker._canonical(marker)),
        "supported_tags_sha256": _digest(worker._canonical(tags)),
    }
    inventory = [["ambient", "1.0"]]
    backend.inventory_result = {
        "schema_version": 1,
        "runtime_fingerprint": fingerprint,
        "marker_environment": marker,
        "supported_tags": tags,
        "installed_inventory": inventory,
        "installed_inventory_sha256": worker._closure_sha256(inventory),
        "satisfied": True,
        "closure": {"distributions": [], "sha256": worker._closure_sha256([])},
    }
    runtime_sha256 = "a" * 64
    request = {
        "schema_version": 1,
        "protocol_version": worker.WORKER_PROTOCOL_VERSION,
        "operation": "probe",
        "worker": _worker_record(runtime_sha256),
        "runtime_role": "shared-agent",
        "image": f"registry.invalid/image@sha256:{'2' * 64}",
        "requirements": [],
        "requirements_sha256": worker._requirements_sha256(()),
        "network": "none",
        "attestation_policy": {
            "code_sha256": worker.inventory_probe_code_sha256(),
            "environment_sha256": worker.inventory_probe_environment_sha256(runtime_sha256),
            "approval_sha256": "3" * 64,
        },
    }
    result, _ = await worker._probe(request, "4" * 64, backend)
    assert result["satisfied"] is True
    assert backend.network == "none"
    assert backend.events[-1] == "cleanup-complete"


@pytest.mark.asyncio
async def test_repeated_cancellation_cannot_detach_cleanup() -> None:
    backend = FakeBackend()
    backend.cleanup_release = asyncio.Event()

    async def operation(_session: worker.RemoteSession) -> None:
        await asyncio.sleep(60)

    task = asyncio.create_task(
        worker._run_in_session(
            backend,
            f"registry.invalid/image@sha256:{'2' * 64}",
            "4" * 64,
            operation,
        )
    )
    while "start" not in backend.events:
        await asyncio.sleep(0)
    task.cancel()
    await backend.cleanup_started.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert "cleanup-complete" not in backend.events
    backend.cleanup_release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert backend.events[-1] == "cleanup-complete"


@pytest.mark.asyncio
async def test_auth_failure_returns_no_private_payload(capsys: pytest.CaptureFixture[str]) -> None:
    backend = FakeBackend(start_error=RuntimeError("private bearer token and session detail"))

    async def operation(_session: worker.RemoteSession) -> None:
        raise AssertionError

    with pytest.raises(RuntimeError):
        await worker._run_in_session(
            backend,
            f"registry.invalid/image@sha256:{'2' * 64}",
            "4" * 64,
            operation,
        )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


@pytest.mark.asyncio
async def test_cleanup_never_globally_drains_after_delete_failure() -> None:
    class Client:
        drained = False

        async def poison_assignment(self, *_args, **_kwargs) -> None:
            return None

        async def delete(self, *_args, **_kwargs) -> None:
            raise RuntimeError("delete failed")

        async def drain_pool(self) -> dict[str, object]:
            self.drained = True
            return {"drained": True, "deleted": [], "failures": {}}

    client = Client()
    session = worker.RemoteSession(
        client=client,
        registry=SimpleNamespace(pop_cleanup_receipt=lambda _name: None),
        sandbox_id="private-session",
        runtime_name="private-runtime",
        outer_session_id="private-outer",
        metadata={},
    )
    backend = worker.PinnedSandoqBackend.__new__(worker.PinnedSandoqBackend)
    with pytest.raises(RuntimeError, match="delete failed"):
        await backend.cleanup(session, "failure", poison=True)
    assert client.drained is False


@pytest.mark.asyncio
async def test_failed_or_cancelled_create_defers_global_recovery_to_controller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCI_RUNNER_TASK_NETWORK", "none")

    class Registry:
        @staticmethod
        def bind_task_context(_context):
            return object()

        @staticmethod
        def reset_task_context(_token) -> None:
            return None

    class Client:
        def __init__(self, *, cancel: bool) -> None:
            self.cancel = cancel
            self.created = asyncio.Event()
            self.release = asyncio.Event()
            self.deleted = False
            self.drained = False

        async def create(self, _request):
            self.created.set()
            if self.cancel:
                await self.release.wait()
            return SimpleNamespace(id="private-assignment")

        async def wait_for_creation(self, _sandbox_id) -> None:
            raise RuntimeError("401 private credential detail")

        async def delete(self, _sandbox_id) -> None:
            self.deleted = True

        async def drain_pool(self) -> dict[str, object]:
            self.drained = True
            return {"drained": True, "deleted": [], "failures": {}}

    for cancel in (False, True):
        client = Client(cancel=cancel)
        backend = worker.PinnedSandoqBackend.__new__(worker.PinnedSandoqBackend)
        backend._registry = Registry()
        backend._client_type = lambda: client
        task = asyncio.create_task(
            backend.start(
                f"registry.invalid/image@sha256:{'2' * 64}",
                "4" * 64,
                network="none",
            )
        )
        await client.created.wait()
        if cancel:
            task.cancel()
            client.release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert client.deleted is False
        else:
            with pytest.raises(RuntimeError, match="401"):
                await task
            assert client.deleted is True
        assert client.drained is False


@pytest.mark.asyncio
async def test_ambiguous_create_without_assignment_handle_defers_global_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCI_RUNNER_TASK_NETWORK", "none")

    class Registry:
        @staticmethod
        def bind_task_context(_context):
            return object()

        @staticmethod
        def reset_task_context(_token) -> None:
            return None

    class Client:
        drained = False
        deleted = False

        async def create(self, _request):
            raise RuntimeError("ambiguous create after remote acceptance")

        async def delete(self, _sandbox_id) -> None:
            self.deleted = True

        async def drain_pool(self) -> dict[str, object]:
            self.drained = True
            return {"drained": True, "deleted": [], "failures": {}}

    client = Client()
    backend = worker.PinnedSandoqBackend.__new__(worker.PinnedSandoqBackend)
    backend._registry = Registry()
    backend._client_type = lambda: client
    with pytest.raises(RuntimeError, match="ambiguous create"):
        await backend.start(
            f"registry.invalid/image@sha256:{'2' * 64}",
            "4" * 64,
            network="none",
        )
    assert client.deleted is False
    assert client.drained is False


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_metadata", [False, True])
async def test_metadata_failure_or_signal_deletes_assignment_without_global_drain(
    monkeypatch: pytest.MonkeyPatch,
    cancel_metadata: bool,
) -> None:
    monkeypatch.setenv("OCI_RUNNER_TASK_NETWORK", "none")

    class Registry:
        @staticmethod
        def bind_task_context(_context):
            return object()

        @staticmethod
        def reset_task_context(_token) -> None:
            return None

    class Client:
        metadata_started = asyncio.Event()
        metadata_release = asyncio.Event()
        deleted = False
        drained = False

        async def create(self, _request):
            return SimpleNamespace(id="private-assignment")

        async def wait_for_creation(self, _sandbox_id) -> None:
            return None

        async def session_metadata(self, _sandbox_id):
            self.metadata_started.set()
            if cancel_metadata:
                await self.metadata_release.wait()
            raise RuntimeError("private metadata failure")

        async def poison_assignment(self, *_args, **_kwargs) -> None:
            return None

        async def delete(self, _sandbox_id) -> None:
            self.deleted = True

        async def drain_pool(self) -> dict[str, object]:
            self.drained = True
            return {"drained": True, "deleted": [], "failures": {}}

    client = Client()
    backend = worker.PinnedSandoqBackend.__new__(worker.PinnedSandoqBackend)
    backend._registry = Registry()
    backend._client_type = lambda: client
    task = asyncio.create_task(
        backend.start(
            f"registry.invalid/image@sha256:{'2' * 64}",
            "4" * 64,
            network="none",
        )
    )
    await asyncio.wait_for(client.metadata_started.wait(), timeout=1)
    if cancel_metadata:
        task.cancel()
        client.metadata_release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
    else:
        with pytest.raises(RuntimeError, match="metadata failure"):
            await asyncio.wait_for(task, timeout=1)
    assert client.deleted is True
    assert client.drained is False


@pytest.mark.asyncio
async def test_repeated_signal_during_delete_cannot_skip_assignment_release() -> None:
    class Client:
        delete_started = asyncio.Event()
        delete_release = asyncio.Event()
        drained = False

        async def poison_assignment(self, *_args, **_kwargs) -> None:
            return None

        async def delete(self, _sandbox_id) -> dict[str, object]:
            self.delete_started.set()
            await self.delete_release.wait()
            return {"nested_recycle_verified": True}

        async def drain_pool(self) -> dict[str, object]:
            self.drained = True
            return {"drained": True, "deleted": [], "failures": {}}

    client = Client()
    pinned = worker.PinnedSandoqBackend.__new__(worker.PinnedSandoqBackend)

    class Backend(FakeBackend):
        async def start(self, image: str, request_sha256: str, *, network: str) -> worker.RemoteSession:
            del image, request_sha256, network
            return worker.RemoteSession(
                client=client,
                registry=SimpleNamespace(pop_cleanup_receipt=lambda _name: {"cleanup_verified": True}),
                sandbox_id="private-assignment",
                runtime_name="private-runtime",
                outer_session_id="private-outer",
                metadata={"environment": "oci-runner-firecracker", "task_network": "none"},
            )

        async def cleanup(
            self,
            session: worker.RemoteSession,
            reason: str,
            *,
            poison: bool,
        ) -> dict[str, object]:
            return await pinned.cleanup(session, reason, poison=poison)

    async def operation(_session: worker.RemoteSession) -> None:
        await asyncio.sleep(60)

    task = asyncio.create_task(
        worker._run_in_session(
            Backend(),
            f"registry.invalid/image@sha256:{'2' * 64}",
            "4" * 64,
            operation,
        )
    )
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.wait_for(client.delete_started.wait(), timeout=1)
    task.cancel()
    await asyncio.sleep(0)
    assert client.drained is False
    client.delete_release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=1)
    assert client.drained is False


@pytest.mark.asyncio
async def test_twenty_four_overlapping_sessions_release_without_global_drain() -> None:
    started = 0
    release = asyncio.Event()
    clients = []

    class Client:
        def __init__(self, index: int) -> None:
            self.index = index
            self.deleted = 0
            self.drained = 0

        async def delete(self, sandbox_id: str) -> dict[str, object]:
            self.deleted += 1
            return {
                "status": "recycled",
                "assignment_id": sandbox_id,
                "outer_session_id": f"outer-{self.index}",
                "nested_recycle_verified": True,
                "shell_deleted": True,
            }

        async def poison_assignment(self, *_args, **_kwargs) -> None:
            raise AssertionError("successful catalog work must remain recyclable")

        async def drain_pool(self) -> dict[str, object]:
            self.drained += 1
            raise AssertionError("normal worker cleanup must not globally drain")

    class Registry:
        def __init__(self, index: int) -> None:
            self.index = index

        def pop_cleanup_receipt(self, runtime_name: str) -> dict[str, object]:
            return {
                "runtime_name": runtime_name,
                "assignment_id": f"assignment-{self.index}",
                "outer_session_id": f"outer-{self.index}",
                "cleanup_verified": True,
                "shell_deleted": True,
            }

    class Backend(worker.PinnedSandoqBackend):
        def __init__(self) -> None:
            pass

        async def start(
            self, image: str, request_sha256: str, *, network: str
        ) -> worker.RemoteSession:
            nonlocal started
            del image, request_sha256
            assert network == "none"
            index = started
            started += 1
            client = Client(index)
            clients.append(client)
            if started == 24:
                release.set()
            return worker.RemoteSession(
                client=client,
                registry=Registry(index),
                sandbox_id=f"assignment-{index}",
                runtime_name=f"runtime-{index}",
                outer_session_id=f"outer-{index}",
                metadata={"environment": "oci-runner-firecracker", "task_network": "none"},
            )

        async def execute(
            self,
            session: worker.RemoteSession,
            command: str,
            *,
            timeout: int,
            environment: dict[str, str] | None = None,
        ) -> tuple[int, str, str]:
            del session, command, timeout, environment
            return 0, '{"default_route":false,"interfaces":["lo"],"network":"none"}', ""

    async def operation(_session: worker.RemoteSession) -> None:
        await release.wait()

    results = await asyncio.gather(
        *(
            worker._run_in_session(
                Backend(),
                f"registry.invalid/image@sha256:{index:064x}",
                f"{index:064x}",
                operation,
            )
            for index in range(1, 25)
        )
    )

    assert started == 24
    assert len(results) == 24
    assert all(client.deleted == 1 and client.drained == 0 for client in clients)


def test_assignment_cleanup_receipt_is_bound_and_never_reads_live_wal(monkeypatch) -> None:
    cleanup = {
        "assignment_id": "private-assignment",
        "runtime_name": "private-runtime",
        "outer_session_id": "private-outer",
        "release": {
            "status": "recycled",
            "assignment_id": "private-assignment",
            "outer_session_id": "private-outer",
            "nested_recycle_verified": True,
            "shell_deleted": True,
        },
        "registry_receipt": {
            "runtime_name": "private-runtime",
            "assignment_id": "private-assignment",
            "outer_session_id": "private-outer",
            "cleanup_verified": True,
            "shell_deleted": True,
        },
    }
    monkeypatch.setattr(
        worker,
        "_wal_snapshot",
        lambda: (_ for _ in ()).throw(AssertionError("live WAL must not be read")),
    )

    receipt = worker._provider_cleanup_record(
        "1" * 64,
        "2" * 64,
        "3" * 64,
        cleanup,
    )

    assert receipt["terminal_state"] == "recycled"
    assert "wal_entry_sha256" not in receipt


def test_assignment_cleanup_rejects_swapped_registry_receipt() -> None:
    cleanup = {
        "assignment_id": "private-assignment",
        "runtime_name": "private-runtime",
        "outer_session_id": "private-outer",
        "release": {
            "status": "recycled",
            "assignment_id": "private-assignment",
            "outer_session_id": "private-outer",
            "nested_recycle_verified": True,
            "shell_deleted": True,
        },
        "registry_receipt": {
            "runtime_name": "private-runtime",
            "assignment_id": "different-assignment",
            "outer_session_id": "private-outer",
            "cleanup_verified": True,
            "shell_deleted": True,
        },
    }

    with pytest.raises(worker.WorkerError, match="^provider_cleanup_unverified$"):
        worker._provider_cleanup_record("1" * 64, "2" * 64, "3" * 64, cleanup)


@pytest.mark.asyncio
async def test_anchor_spans_worker_handoff_gap_and_performs_one_terminal_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = FakeBackend()
    artifact_directory = tmp_path / "anchor-artifacts"
    artifact_directory.mkdir(mode=0o700)
    request_sha256 = "4" * 64
    run_nonce = "5" * 32
    request = {
        "schema_version": 1,
        "protocol_version": worker.WORKER_PROTOCOL_VERSION,
        "operation": "anchor",
        "worker": _worker_record(),
        "run_nonce": run_nonce,
        "network": "control-plane",
        "anchor_contract": {
            "active_client_required": True,
            "heartbeat_interval_seconds": worker.PROVIDER_ANCHOR_HEARTBEAT_INTERVAL_SECONDS,
            "sole_terminal_drain": True,
            "zero_live_wal_required": True,
        },
    }
    monkeypatch.setattr(worker, "_wal_snapshot", lambda: (_digest("empty-wal"), 0))
    anchor = asyncio.create_task(
        worker._anchor(request, request_sha256, artifact_directory, backend)
    )
    ready_path = artifact_directory / "anchor-ready.json"
    for _ in range(100):
        if ready_path.exists():
            break
        await asyncio.sleep(0.01)
    assert ready_path.exists()
    assert backend.events == ["anchor"]

    async def operation(_session: worker.RemoteSession) -> None:
        await asyncio.sleep(0)

    await asyncio.gather(
        *(
            worker._run_in_session(
                backend,
                f"registry.invalid/image@sha256:{index:064x}",
                f"{index:064x}",
                operation,
            )
            for index in range(1, 25)
        )
    )
    await asyncio.sleep(0)
    assert not anchor.done()
    assert "recover" not in backend.events

    stop_path = artifact_directory / "anchor-stop.json"
    stop_path.write_bytes(
        worker._canonical(
            {
                "schema_version": 1,
                "request_sha256": request_sha256,
                "run_nonce": run_nonce,
                "phase": "final",
            }
        )
    )
    stop_path.chmod(0o400)
    result = await anchor

    assert result["phase"] == "final"
    assert result["remaining_sessions"] == 0
    assert backend.events.count("recover") == 1
    assert backend.events[-1] == "recover"


@pytest.mark.asyncio
async def test_repeated_anchor_cancellation_cannot_skip_terminal_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SlowRecoveryBackend(FakeBackend):
        def __init__(self) -> None:
            super().__init__()
            self.recovery_started = asyncio.Event()
            self.recovery_release = asyncio.Event()

        async def recover(self, reason: str) -> dict[str, object]:
            del reason
            self.events.append("recover")
            self.recovery_started.set()
            await self.recovery_release.wait()
            return {"drained": True, "deleted": [], "failures": {}}

    backend = SlowRecoveryBackend()
    artifact_directory = tmp_path / "anchor-artifacts"
    artifact_directory.mkdir(mode=0o700)
    request_sha256 = "6" * 64
    request = {
        "schema_version": 1,
        "protocol_version": worker.WORKER_PROTOCOL_VERSION,
        "operation": "anchor",
        "worker": _worker_record(),
        "run_nonce": "7" * 32,
        "network": "control-plane",
        "anchor_contract": {
            "active_client_required": True,
            "heartbeat_interval_seconds": worker.PROVIDER_ANCHOR_HEARTBEAT_INTERVAL_SECONDS,
            "sole_terminal_drain": True,
            "zero_live_wal_required": True,
        },
    }
    monkeypatch.setattr(worker, "_wal_snapshot", lambda: (_digest("empty-wal"), 0))
    anchor = asyncio.create_task(
        worker._anchor(request, request_sha256, artifact_directory, backend)
    )
    ready_path = artifact_directory / "anchor-ready.json"
    for _ in range(100):
        if ready_path.exists():
            break
        await asyncio.sleep(0.01)
    assert ready_path.exists()

    anchor.cancel()
    await backend.recovery_started.wait()
    anchor.cancel()
    await asyncio.sleep(0)
    assert not anchor.done()
    backend.recovery_release.set()
    with pytest.raises(asyncio.CancelledError):
        await anchor
    assert backend.events.count("recover") == 1


@pytest.mark.asyncio
async def test_anchor_heartbeat_failure_runs_terminal_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailedHeartbeatBackend(FakeBackend):
        async def anchor_heartbeat(self) -> dict[str, object]:
            self.events.append("anchor-heartbeat")
            raise RuntimeError("synthetic heartbeat failure")

    backend = FailedHeartbeatBackend()
    artifact_directory = tmp_path / "anchor-artifacts"
    artifact_directory.mkdir(mode=0o700)
    monkeypatch.setattr(worker, "PROVIDER_ANCHOR_HEARTBEAT_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(worker, "_wal_snapshot", lambda: (_digest("empty-wal"), 0))
    request = {
        "schema_version": 1,
        "protocol_version": worker.WORKER_PROTOCOL_VERSION,
        "operation": "anchor",
        "worker": _worker_record(),
        "run_nonce": "8" * 32,
        "network": "control-plane",
        "anchor_contract": {
            "active_client_required": True,
            "heartbeat_interval_seconds": 0.01,
            "sole_terminal_drain": True,
            "zero_live_wal_required": True,
        },
    }

    with pytest.raises(RuntimeError, match="synthetic heartbeat failure"):
        await worker._anchor(request, "9" * 64, artifact_directory, backend)
    assert backend.events == ["anchor", "anchor-heartbeat", "recover"]


@pytest.mark.asyncio
async def test_recovery_is_completed_before_a_later_lease(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wal = tmp_path / "pool.wal"
    wal.write_text("")
    wal.chmod(0o600)
    monkeypatch.setenv("OCI_RUNNER_POOL_WAL", str(wal))
    backend = FakeBackend()
    request = {
        "schema_version": 1,
        "protocol_version": worker.WORKER_PROTOCOL_VERSION,
        "operation": "recover",
        "worker": _worker_record(),
        "run_nonce": "0" * 32,
        "phase": "startup",
        "network": "control-plane",
        "recovery_contract": {
            "durable_provider_wal": True,
            "drain_or_retire_orphans": True,
            "require_cleanup_receipts": True,
        },
    }
    result = await worker._recover(request, "4" * 64, backend)
    assert result["remaining_sessions"] == 0
    assert result["phase"] == "startup"
    await backend.start(f"registry.invalid/image@sha256:{'2' * 64}", "4" * 64, network="none")
    assert backend.events[:2] == ["recover", "start"]


@pytest.mark.asyncio
async def test_binary_builder_runs_only_in_isolated_trusted_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = FakeBackend()
    builder_image = f"registry.invalid/catalog-builder@sha256:{'1' * 64}"
    monkeypatch.setenv("SANDOQ_CATALOG_BUILDER_IMAGE", builder_image)
    filename, wheel_payload = _wheel()
    wheel_sha256 = _digest(wheel_payload)
    root = f"{worker.RUNTIME_ROOT}/build-{'4' * 64}/wheels"
    report_download = {
        "url": "https://index.invalid/root_pkg.whl",
        "archive_info": {"hashes": {"sha256": wheel_sha256}},
    }
    report = {
        "version": "1",
        "pip_version": "24.3.1",
        "install": [
            {
                "download_info": report_download,
                "metadata": {"name": "root-pkg", "version": "1.0.0"},
            }
        ],
        "environment": {},
    }
    backend.downloads[f"{worker.RUNTIME_ROOT}/build-{'4' * 64}/report.json"] = worker._canonical(report)
    backend.downloads[f"{root}/{filename}"] = wheel_payload
    marker_environment: dict[str, str] = {}
    supported_tags = ["cp312-cp312-manylinux_2_17_x86_64", "cp312-none-any"]
    fingerprint = {
        "schema_version": 1,
        "implementation": "cpython",
        "python_full_version": "3.12.8",
        "abi": "abi",
        "platform": "linux",
        "machine": "x86_64",
        "libc": "glibc",
        "pip_version": "24.3.1",
        "marker_environment_sha256": _digest(worker._canonical(marker_environment)),
        "supported_tags_sha256": _digest(worker._canonical(supported_tags)),
    }
    worker_record = _worker_record()
    toolchain = {
        "schema_version": 1,
        "python_version": "3.12.8",
        "pip_version": "24.3.1",
        "resolver": "pip",
        "resolver_version": "24.3.1",
        "builder_code_sha256": worker._builder_code_sha256(worker_record),
        "build_environment_sha256": worker._builder_environment_sha256(worker_record, builder_image),
    }
    snapshot = _digest(
        worker._canonical({"schema_version": 1, "kind": "pip-report-download-info", "download_info": report_download})
    )
    binary_policy = {
        "schema_version": 1,
        "distribution": "root-pkg",
        "version": "1.0.0",
        "filename": filename,
        "size": len(wheel_payload),
        "sha256": wheel_sha256,
        "source_url_sha256": _digest("https://index.invalid/root_pkg.whl"),
        "source_snapshot_sha256": snapshot,
    }
    approved_binaries = [_digest(worker._canonical(binary_policy))]
    approved_sources: list[str] = []
    approved_toolchains = [_digest(worker._canonical(toolchain))]
    request = {
        "schema_version": 1,
        "protocol_version": worker.WORKER_PROTOCOL_VERSION,
        "operation": "build",
        "worker": worker_record,
        "image": f"registry.invalid/image@sha256:{'2' * 64}",
        "requirements": ["root-pkg==1.0.0"],
        "requirements_sha256": worker._requirements_sha256(("root-pkg==1.0.0",)),
        "compatibility": {
            "runtime_fingerprint": fingerprint,
            "runtime_fingerprint_sha256": _digest(worker._canonical(fingerprint)),
            "marker_environment": marker_environment,
            "supported_tags": supported_tags,
        },
        "policy": {
            "source_policy_sha256": "7" * 64,
            "source_policy_approval_sha256": "8" * 64,
            "approved_binary_artifacts": approved_binaries,
            "approved_binary_artifacts_sha256": worker._allowlist_sha256("binary-artifacts", approved_binaries),
            "approved_source_attestations": approved_sources,
            "approved_source_attestations_sha256": worker._allowlist_sha256("source-attestations", approved_sources),
            "approved_toolchains": approved_toolchains,
            "approved_toolchains_sha256": worker._allowlist_sha256("toolchains", approved_toolchains),
        },
        "scope_policy": "discover",
        "network": "trusted-builder",
        "artifact_contract": {
            "filename": "wheelhouse.tar",
            "deterministic_format": "ustar-sorted-zero-mtime-v1",
            "binary_only_unless_source_attested": True,
        },
    }
    result, _ = await worker._build(
        request,
        "4" * 64,
        tmp_path,
        backend,
    )
    assert result["scope"] == "universal"
    assert result["wheels"][0]["origin"] == "binary"
    assert backend.network == "trusted-builder"
    assert backend.started_images == [builder_image]
    assert builder_image != request["image"]
    pip_commands = [command for command in backend.commands if " -m pip " in f" {command} "]
    assert len(pip_commands) == 2
    assert all("--only-binary=:all:" in command for command in pip_commands)


@pytest.mark.asyncio
async def test_binary_builder_rejects_unbound_allowlist_before_resolution(tmp_path: Path) -> None:
    backend = FakeBackend()
    builder_image = f"registry.invalid/catalog-builder@sha256:{'1' * 64}"
    marker_environment: dict[str, str] = {}
    supported_tags = ["cp312-cp312-manylinux_2_17_x86_64", "cp312-none-any"]
    fingerprint = {
        "schema_version": 1,
        "implementation": "cpython",
        "python_full_version": "3.12.8",
        "abi": "abi",
        "platform": "linux",
        "machine": "x86_64",
        "libc": "glibc",
        "pip_version": "24.3.1",
        "marker_environment_sha256": _digest(worker._canonical(marker_environment)),
        "supported_tags_sha256": _digest(worker._canonical(supported_tags)),
    }
    request = {
        "worker": _worker_record(),
        "requirements": ["root-pkg==1.0.0"],
        "compatibility": {
            "runtime_fingerprint": fingerprint,
            "runtime_fingerprint_sha256": _digest(worker._canonical(fingerprint)),
            "marker_environment": marker_environment,
            "supported_tags": supported_tags,
        },
        "policy": {
            "source_policy_sha256": "7" * 64,
            "source_policy_approval_sha256": "8" * 64,
            "approved_binary_artifacts": [],
            "approved_binary_artifacts_sha256": "9" * 64,
            "approved_source_attestations": [],
            "approved_source_attestations_sha256": worker._allowlist_sha256("source-attestations", []),
            "approved_toolchains": [],
            "approved_toolchains_sha256": worker._allowlist_sha256("toolchains", []),
        },
        "scope_policy": "discover",
        "image": f"registry.invalid/image@sha256:{'2' * 64}",
    }
    session = await backend.start(builder_image, "4" * 64, network="trusted-builder")
    with pytest.raises(worker.WorkerError, match="worker_request_invalid"):
        await worker._build_wheelhouse(
            request,
            tmp_path,
            backend,
            session,
            "4" * 64,
            builder_image,
        )
    assert backend.commands == []


def test_wrapper_binds_module_and_isolated_no_bytecode_interpreter() -> None:
    package_root = Path(worker.__file__).resolve().parents[1]
    wrapper = package_root / "bin" / "sandoq-offline-catalog-worker"
    text = wrapper.read_text()
    module_payload = Path(worker.__file__).read_bytes()
    assert " -I -B -S -c " in text
    assert _digest(module_payload) in text
    assert f"before.st_size != {len(module_payload)}" in text
    assert "stat.S_ISREG" in text
    assert "before.st_nlink != 1" in text
    assert "exec(compile(payload" in text


def test_print_contract_is_task_and_credential_free(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    activated = False

    def activate() -> None:
        nonlocal activated
        activated = True

    def reject_operational_validation() -> None:
        raise AssertionError("print-contract must not validate operational credentials")

    monkeypatch.setattr(worker, "_activate_worker_site", activate)
    monkeypatch.setattr(worker, "_validate_environment", reject_operational_validation)
    monkeypatch.setattr(worker, "worker_runtime_sha256", lambda: "1" * 64)
    monkeypatch.setenv("SANDOQ_CATALOG_WORKER_SITE_MANIFEST_SHA256", "2" * 64)
    monkeypatch.setenv("SANDOQ_CATALOG_PYTHON_RUNTIME_MANIFEST_SHA256", "3" * 64)
    monkeypatch.setenv("SANDOQ_CATALOG_WORKER_PROVISION_IDENTITY_SHA256", "4" * 64)
    monkeypatch.delenv("SANDOQ_CATALOG_BUILDER_IMAGE", raising=False)

    assert worker.main(["--print-contract"]) == 0
    contract = json.loads(capsys.readouterr().out)
    assert activated is True
    assert contract["worker_runtime_sha256"] == "1" * 64
    assert contract["worker_site_manifest_sha256"] == "2" * 64
    assert contract["python_runtime_manifest_sha256"] == "3" * 64
    assert contract["worker_provision_identity_sha256"] == "4" * 64
    assert "builder_image_sha256" not in contract


def test_provider_source_is_copied_into_an_exact_private_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"VALUE = 1\n"
    source = tmp_path / "source"
    package = source / "sandoq_provider"
    package.mkdir(parents=True)
    (package / "__init__.py").write_bytes(payload)
    (package / "README.md").write_text("not imported")
    record = {
        "schema_version": 1,
        "provider_commit": worker.PINNED_PROVIDER_COMMIT,
        "files": [{"path": "__init__.py", "sha256": _digest(payload), "size": len(payload)}],
    }
    monkeypatch.setattr(worker, "_PROVIDER_FILES", {"__init__.py": (_digest(payload), len(payload))})
    monkeypatch.setattr(worker, "PINNED_PROVIDER_SOURCE_SHA256", _digest(worker._canonical(record)))
    monkeypatch.setenv("SANDOQ_PROVIDER_ROOT", str(source))
    destination = tmp_path / "staged"
    original_path = list(worker.sys.path)
    try:
        worker._stage_provider_source(destination)
        assert sorted(path.name for path in destination.iterdir()) == ["sandoq_provider"]
        assert sorted(path.name for path in (destination / "sandoq_provider").iterdir()) == ["__init__.py"]
        assert (destination / "sandoq_provider" / "__init__.py").stat().st_mode & 0o777 == 0o400
        (destination / "sandoq_provider" / "extra.so").write_bytes(b"unapproved")
        with pytest.raises(worker.WorkerError, match="provider_source_invalid"):
            worker._provider_source_record(destination, exact_staged_tree=True)
    finally:
        worker.sys.path[:] = original_path
        worker._STAGED_PROVIDER_ROOT = None


def test_runtime_distribution_record_allows_confined_parent_segments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "runtime"
    site = root / "lib" / "python3.12" / "site-packages"
    script = root / "bin" / "tool"
    site.mkdir(parents=True)
    script.parent.mkdir()
    script.write_bytes(b"#!/bin/sh\n")
    script.chmod(0o500)
    for directory in (site, site.parent, site.parent.parent, script.parent, root):
        directory.chmod(0o500)
    try:
        manifest = worker._runtime_site_tree_record(root, "lib/python3.12/site-packages")
        monkeypatch.setattr(worker, "_WORKER_SITE_ROOT", root)
        monkeypatch.setattr(worker, "_WORKER_SITE_RECORD", manifest)

        class Distribution:
            version = "1.0"
            files = [worker.PurePosixPath("../../../bin/tool")]

            @staticmethod
            def locate_file(relative):
                return site / str(relative)

        record, claimed = worker._distribution_record("example", Distribution())
        assert record["files"] == [{"path": "bin/tool", "sha256": _digest(b"#!/bin/sh\n"), "size": 10}]
        assert claimed == {"bin/tool"}
    finally:
        for directory in (site, site.parent, site.parent.parent, script.parent, root):
            directory.chmod(0o700)
        script.chmod(0o600)


def test_runtime_distribution_names_reject_duplicate_canonical_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(worker, "_WORKER_SITE_DIRECTORY", tmp_path)
    distributions = [
        SimpleNamespace(metadata={"Name": "same-name"}),
        SimpleNamespace(metadata={"Name": "same_name"}),
    ]
    monkeypatch.setattr(worker.importlib.metadata, "distributions", lambda **_kwargs: distributions)
    with pytest.raises(worker.WorkerError, match="worker_runtime_invalid"):
        worker._runtime_distributions()


def test_runtime_site_ownership_rejects_unowned_importable_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        worker,
        "_WORKER_SITE_RECORD",
        {
            "directories": [{"path": "site", "mode": 0o500}],
            "files": [
                {"path": "site/owned.py", "mode": 0o400, "size": 1, "sha256": "1" * 64},
                {"path": "site/extra.py", "mode": 0o400, "size": 1, "sha256": "2" * 64},
            ],
        },
    )
    with pytest.raises(worker.WorkerError, match="worker_runtime_extra_file"):
        worker._validate_runtime_site_ownership({"site/owned.py"})


def test_worker_site_manifest_rejects_extra_file_after_sealing(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    site = root / "site"
    site.mkdir(parents=True)
    owned = site / "owned.py"
    owned.write_bytes(b"x")
    owned.chmod(0o400)
    site.chmod(0o500)
    root.chmod(0o500)
    manifest_path = tmp_path / "manifest.json"
    try:
        manifest = worker._runtime_site_tree_record(root, "site")
        manifest_payload = worker._canonical(manifest)
        worker._atomic_private_write(manifest_path, manifest_payload)
        observed, observed_site = worker._verified_worker_site(root, manifest_path, _digest(manifest_payload))
        assert observed == manifest
        assert observed_site == site

        root.chmod(0o700)
        site.chmod(0o700)
        extra = site / "extra.py"
        extra.write_bytes(b"y")
        extra.chmod(0o400)
        site.chmod(0o500)
        root.chmod(0o500)
        with pytest.raises(worker.WorkerError, match="worker_site_invalid"):
            worker._verified_worker_site(root, manifest_path, _digest(manifest_payload))
    finally:
        root.chmod(0o700)
        site.chmod(0o700)
        for path in site.iterdir():
            path.chmod(0o600)


def test_site_manifest_cli_publishes_only_aggregate_counts(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "runtime"
    site = root / "site"
    site.mkdir(parents=True)
    payload = site / "module.py"
    payload.write_bytes(b"value = 1\n")
    payload.chmod(0o400)
    site.chmod(0o500)
    root.chmod(0o500)
    manifest_path = tmp_path / "manifest.json"
    try:
        result = worker.main(
            [
                "--write-site-manifest",
                str(manifest_path),
                "--site-root",
                str(root),
                "--site-directory",
                "site",
            ]
        )
        assert result == 0
        receipt = json.loads(capsys.readouterr().out)
        assert receipt == {"directories": 1, "files": 1, "schema_version": 1}
        assert str(root) not in json.dumps(receipt)
        assert manifest_path.stat().st_mode & 0o777 == 0o400
    finally:
        root.chmod(0o700)
        site.chmod(0o700)
        payload.chmod(0o600)


def test_environment_contract_requires_rotator_metadata_and_no_fallback() -> None:
    assert "OCI_RUNNER_ECR_TOKEN_METADATA_PATH" in worker._REQUIRED_ENVIRONMENT_NAMES
    assert "SANDOQ_CATALOG_PYTHON_RUNTIME_MANIFEST_SHA256" in worker._REQUIRED_ENVIRONMENT_NAMES
    assert "SANDOQ_CATALOG_WORKER_PROVISION_IDENTITY_SHA256" in worker._REQUIRED_ENVIRONMENT_NAMES
    assert worker._REQUIRED_ENVIRONMENT["OCI_RUNNER_ALLOW_DOCKERHUB_FALLBACK"] == "0"
    assert worker._REQUIRED_ENVIRONMENT["OCI_RUNNER_TASK_NETWORK"] == "none"
    assert worker._REQUIRED_ENVIRONMENT["SANDOQ_CATALOG_EXCLUSIVE_POOL"] == "1"


def test_shared_pool_policy_bounds_parallel_worker_processes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pool_root = tmp_path / "pool"
    pool_root.mkdir(mode=0o700)
    wal_root = tmp_path / "wal"
    wal_root.mkdir(mode=0o700)
    values = {
        "OCI_RUNNER_ENVIRONMENT": "oci-runner-firecracker",
        "OCI_RUNNER_POOL_SOCKET": str(pool_root / "catalog.sock"),
        "OCI_RUNNER_POOL_WAL": str(wal_root / "catalog.wal.jsonl"),
        "OCI_RUNNER_TASK_NETWORK": "none",
        "SANDOQ_CATALOG_EXCLUSIVE_POOL": "1",
        "SANDOQ_OWNER": "synthetic-exclusive-owner",
        "VF_SANDBOX_PROVIDER": "sandoq",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    names = tuple(sorted(values))
    environment_sha256 = materializer.worker_environment_sha256(names)
    policy = materializer.WorkerPolicy(
        executable_sha256="1" * 64,
        runtime_sha256="2" * 64,
        materializer_code_sha256=materializer.materializer_controller_code_sha256(),
        cleanup_receipt_verifier_sha256="3" * 64,
        environment_sha256=environment_sha256,
        recovery_scope_sha256=materializer.worker_recovery_scope_sha256(environment_sha256),
        ecr_rotator_sha256=None,
        environment_names=names,
        recovery_timeout_seconds=30,
        probe_timeout_seconds=30,
        build_timeout_seconds=30,
        validate_timeout_seconds=30,
        probe_concurrency=25,
        build_concurrency=4,
        validate_concurrency=24,
    )
    with pytest.raises(materializer.OfflineCatalogError, match="worker_shared_pool_concurrency_invalid"):
        materializer._parse_worker_policy(policy.record())

    bounded = materializer.WorkerPolicy(**{**policy.__dict__, "probe_concurrency": 24})
    assert materializer._parse_worker_policy(bounded.record()).probe_concurrency == 24


def test_operational_main_redacts_raw_failure_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def fail(_args) -> None:
        print("private task and credential")
        raise RuntimeError("private task and credential")

    monkeypatch.setattr(worker, "_run_worker", fail)
    result = worker.main(
        [
            "--request",
            "/private/request.json",
            "--request-sha256",
            "0" * 64,
            "--response",
            "/private/response.json",
            "--artifact-dir",
            "/private/artifacts",
        ]
    )
    assert result == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
