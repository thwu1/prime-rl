from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import signal
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
DIAGNOSTIC = ROOT / "user/tianhaowu/terminal_bench_vmvm/vmvm_owner_lifecycle_diagnostic_v4"
TOKEN = "599a27d3de4dafba2f59981c"
CREATOR_PATH = HERE / f"create_vmvm_owner_lifecycle_authorization_v4_{TOKEN}.py"
RECOVERY_PATH = HERE / f"vmvm_v4_recover_and_create_auth_{TOKEN}.py"
LAUNCH_PATH = HERE / f"vmvm_v4_recover_and_launch_{TOKEN}.py"
INVOCATION_PATH = HERE / f"invoke_vmvm_owner_lifecycle_v4_{TOKEN}.py"


def load_module(name: str, path: Path) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def creator() -> Any:
    return load_module("vmvm_v4_candidate_creator", CREATOR_PATH)


@pytest.fixture(scope="module")
def recovery() -> Any:
    return load_module("vmvm_v4_candidate_recovery", RECOVERY_PATH)


@pytest.fixture(scope="module")
def launch() -> Any:
    return load_module("vmvm_v4_candidate_launch", LAUNCH_PATH)


@pytest.fixture(scope="module")
def invocation() -> Any:
    return load_module("vmvm_v4_candidate_invocation", INVOCATION_PATH)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_exact_v4_hash_chain_and_fresh_token(creator: Any, recovery: Any, launch: Any) -> None:
    diagnostic_launcher = DIAGNOSTIC / "launch_vmvm_owner_lifecycle_v4.py"
    expected_launcher_sha = digest(diagnostic_launcher)
    assert expected_launcher_sha == "354595d2f0822052d6b42cfe12233d9629f75c82a01060745c33ca308000a731"
    assert creator.LAUNCHER_SHA256 == expected_launcher_sha
    assert launch.LAUNCHER_SHA256 == expected_launcher_sha
    assert recovery.CREATOR_V4_SHA256 == digest(CREATOR_PATH)
    assert launch.RECOVERY_HELPER_SHA256 == digest(RECOVERY_PATH)
    assert creator.JOB_TOKEN == TOKEN
    assert creator.JOB_NAME == f"vmvm-owner-v4-{TOKEN}"
    assert creator.AUTHORIZATION == launch.AUTHORIZATION
    assert creator.AUTHORIZATION.name == f"vmvm_owner_lifecycle_9d7841b36_v4_{TOKEN}.authorization.json"
    assert creator.LAUNCHER.name == "launch_vmvm_owner_lifecycle_v4.py"
    assert launch.LAUNCHER == creator.LAUNCHER
    assert creator.BUNDLE_SHA256 == {
        "finalizer": digest(DIAGNOSTIC / "finalize_vmvm_owner_lifecycle_v4.py"),
        "launcher": digest(DIAGNOSTIC / "launch_vmvm_owner_lifecycle_v4.py"),
        "probe": digest(DIAGNOSTIC / "probe_vmvm_owner_lifecycle_v4.py"),
        "readme": digest(DIAGNOSTIC / "README.md"),
        "tests": digest(DIAGNOSTIC / "test_vmvm_owner_lifecycle_v4.py"),
        "wrapper": digest(DIAGNOSTIC / "run_vmvm_owner_lifecycle_v4.sbatch"),
    }


def test_authorizer_preserves_launcher_owned_source_runtime_and_site_contract(creator: Any) -> None:
    source = CREATOR_PATH.read_text()
    for expression in (
        '"revision": launcher.SOURCE_REVISION',
        '"tree": launcher.SOURCE_TREE',
        '"verifiers_revision": launcher.VERIFIERS_REVISION',
        '"renderers_revision": launcher.RENDERERS_REVISION',
        '"pydantic_config_revision": launcher.PYDANTIC_CONFIG_REVISION',
        '"backend_sha256": launcher.BACKEND_SHA256',
        "site_fd = launcher.open_bound_directory(launcher.X86_SITE)",
        '"inventory": site_inventory',
        '"uv": {"path": str(launcher.X86_UV), "sha256": launcher.X86_UV_SHA256}',
        '"sha256": launcher.VACLI_SHA256',
    ):
        assert expression in source
    assert creator.FILE_MODES == {
        "launcher": ("launch_vmvm_owner_lifecycle_v4.py", 0o500),
        "probe": ("probe_vmvm_owner_lifecycle_v4.py", 0o500),
        "wrapper": ("run_vmvm_owner_lifecycle_v4.sbatch", 0o500),
        "finalizer": ("finalize_vmvm_owner_lifecycle_v4.py", 0o500),
        "readme": ("README.md", 0o400),
        "tests": ("test_vmvm_owner_lifecycle_v4.py", 0o400),
    }


def test_private_v2_metadata_hashes_are_runtime_only(recovery: Any, launch: Any) -> None:
    assert recovery.METADATA_HASH_ENV == launch.METADATA_HASH_ENV
    for path in (RECOVERY_PATH, LAUNCH_PATH, INVOCATION_PATH):
        source = path.read_text()
        for stale_constant in (
            "AUTH_V2_SHA256 =",
            "FAILURE_V2_SHA256 =",
            "RECEIPT_V2_SHA256 =",
            "ENVIRONMENT_V2_SHA256 =",
        ):
            assert stale_constant not in source
    assert set(recovery.METADATA_HASH_ENV) == {
        "authorization",
        "environment",
        "failure",
        "receipt",
    }


@pytest.mark.parametrize("fixture_name", ("creator", "recovery", "launch"))
def test_signals_are_blocked_before_handler_installation(
    fixture_name: str,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = request.getfixturevalue(fixture_name)
    events: list[tuple[str, object]] = []
    previous = {signal.SIGUSR1}

    def fake_mask(operation: int, mask: set[signal.Signals]) -> set[signal.Signals]:
        events.append(("mask", (operation, frozenset(mask))))
        return previous

    def fake_signal(signum: signal.Signals, _handler: object) -> None:
        events.append(("handler", signum))

    monkeypatch.setattr(module.signal, "pthread_sigmask", fake_mask)
    monkeypatch.setattr(module.signal, "signal", fake_signal)
    module.install_signal_handlers()
    assert events[0] == ("mask", (signal.SIG_BLOCK, frozenset(module.HANDLED_SIGNALS)))
    assert events[-1] == ("mask", (signal.SIG_SETMASK, frozenset(previous)))
    assert {value for kind, value in events[1:-1] if kind == "handler"} == module.HANDLED_SIGNALS


@pytest.mark.parametrize("fixture_name", ("recovery", "launch"))
def test_stable_reads_close_every_fd_before_signal_unmask(
    fixture_name: str,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = request.getfixturevalue(fixture_name)
    payload = b"descriptor-bound\n"
    source = tmp_path / "source"
    source.write_bytes(payload)
    source.chmod(0o600)
    open_descriptors: set[int] = set()
    real_open = os.open
    real_close = os.close

    def tracked_open(*args: Any, **kwargs: Any) -> int:
        descriptor = real_open(*args, **kwargs)
        open_descriptors.add(descriptor)
        return descriptor

    def tracked_close(descriptor: int) -> None:
        real_close(descriptor)
        open_descriptors.remove(descriptor)

    def tracked_mask(operation: int, _mask: set[signal.Signals]) -> set[signal.Signals]:
        if operation == signal.SIG_SETMASK:
            assert not open_descriptors
        return set()

    monkeypatch.setattr(module.os, "open", tracked_open)
    monkeypatch.setattr(module.os, "close", tracked_close)
    monkeypatch.setattr(module.signal, "pthread_sigmask", tracked_mask)
    result = module.stable_file(
        source,
        mode=0o600,
        expected=hashlib.sha256(payload).hexdigest(),
        **({"maximum": 1024} if fixture_name == "launch" else {}),
    )
    assert result == payload
    assert not open_descriptors


def test_creator_load_and_publish_close_fds_before_unmask(
    creator: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    launcher = tmp_path / "launcher.py"
    raw = b"MARKER = 7\n"
    launcher.write_bytes(raw)
    launcher.chmod(0o500)
    authorization = tmp_path / "authorization.json"
    open_descriptors: set[int] = set()
    real_open = os.open
    real_close = os.close

    def tracked_open(*args: Any, **kwargs: Any) -> int:
        descriptor = real_open(*args, **kwargs)
        open_descriptors.add(descriptor)
        return descriptor

    def tracked_close(descriptor: int) -> None:
        real_close(descriptor)
        open_descriptors.remove(descriptor)

    def tracked_mask(operation: int, _mask: set[signal.Signals]) -> set[signal.Signals]:
        if operation == signal.SIG_SETMASK:
            assert not open_descriptors
        return set()

    monkeypatch.setattr(creator, "LAUNCHER", launcher)
    monkeypatch.setattr(creator, "LAUNCHER_SHA256", hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(creator, "OWNER_UID", os.getuid())
    monkeypatch.setattr(creator.os, "open", tracked_open)
    monkeypatch.setattr(creator.os, "close", tracked_close)
    monkeypatch.setattr(creator.signal, "pthread_sigmask", tracked_mask)
    loaded = creator.load_launcher()
    assert loaded.MARKER == 7
    assert not open_descriptors
    creator.publish_exclusive(authorization, b"{}")
    assert authorization.read_bytes() == b"{}"
    assert stat.S_IMODE(authorization.stat().st_mode) == 0o400
    assert not open_descriptors


def test_recovery_lineage_returns_only_hash_bound_proxy(
    recovery: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy = "test-only-proxy"
    environment = {
        "X2P_ENV": "test-environment",
        "X2P_CFG_ENV": "test-config",
        "X2P_PROXY_URL": proxy,
    }
    x2p = {name: {"sha256": hashlib.sha256(value.encode()).hexdigest()} for name, value in environment.items()}
    auth_body = {
        "artifact_type": "vmvm_owner_lifecycle_diagnostic_authorization_v2",
        "credentials": {"tls": {}, "x2p": x2p},
        "launch": {"job_name": recovery.JOB_NAME_V2},
        "schema_version": 1,
        "state": "approved",
    }
    authorization_sha = hashlib.sha256(recovery.canonical(auth_body)).hexdigest()
    auth_raw = recovery.canonical({**auth_body, "authorization_sha256": authorization_sha})
    job = {"cluster": "fair-cw-use2-3", "job_id": "123", "job_name": recovery.JOB_NAME_V2}
    environment_raw = b"".join(f"{name}={value}".encode() + b"\0" for name, value in environment.items())
    receipt_body = {
        "artifact_type": "vmvm_owner_lifecycle_submission_receipt_v2",
        "authorization_file_sha256": hashlib.sha256(auth_raw).hexdigest(),
        "authorization_sha256": authorization_sha,
        "environment_sha256": hashlib.sha256(environment_raw).hexdigest(),
        "job": job,
        "production_authorized": False,
        "release_attempts": 1,
        "release_outcome": "completed",
        "state": "submitted",
        "submission_attempts": 1,
    }
    receipt_raw = recovery.canonical(receipt_body) + b"\n"
    failure_raw = (
        recovery.canonical(
            {
                "artifact_type": "vmvm_owner_lifecycle_probe_failure_receipt_v2",
                "authorization_file_sha256": hashlib.sha256(auth_raw).hexdigest(),
                "authorization_sha256": authorization_sha,
                "backend_sha256": recovery.BACKEND_SHA256,
                "cleanup_status": "verified",
                "diagnostic_only": True,
                "environment_sha256": hashlib.sha256(environment_raw).hexdigest(),
                "failure_class": "site_binding_invalid",
                "job": job,
                "model_endpoint_accessed": False,
                "production_authorized": False,
                "schema_version": 1,
                "source_revision": recovery.SOURCE_REVISION,
                "state": "failed",
                "submission_receipt_sha256": hashlib.sha256(receipt_raw).hexdigest(),
                "task_data_accessed": False,
            }
        )
        + b"\n"
    )
    payloads = {
        recovery.AUTH_V2: auth_raw,
        recovery.FAILURE_V2: failure_raw,
        recovery.RECEIPT_V2: receipt_raw,
        recovery.ENVIRONMENT_V2: environment_raw,
    }
    metadata = {
        "authorization": hashlib.sha256(auth_raw).hexdigest(),
        "environment": hashlib.sha256(environment_raw).hexdigest(),
        "failure": hashlib.sha256(failure_raw).hexdigest(),
        "receipt": hashlib.sha256(receipt_raw).hexdigest(),
    }

    def fake_stable_file(path: Path, *, mode: int, expected: str, maximum: int = 1 << 20) -> bytes:
        assert mode == 0o400
        raw = payloads[path]
        assert len(raw) <= maximum
        assert hashlib.sha256(raw).hexdigest() == expected
        return raw

    monkeypatch.setattr(recovery, "stable_file", fake_stable_file)
    monkeypatch.setattr(
        recovery.os,
        "environ",
        {"X2P_ENV": environment["X2P_ENV"], "X2P_CFG_ENV": environment["X2P_CFG_ENV"]},
    )
    assert recovery.recover_proxy(metadata) == proxy


def test_launch_outer_environment_rejects_preexisting_proxy(
    launch: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = {
        "HOME": "/storage/home/tianhaowu",
        "LANG": "C",
        "LC_ALL": "C",
        "LOGNAME": "tianhaowu",
        "PATH": "/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "TMUX": "test",
        "TMUX_PANE": "%0",
        "TZ": "UTC",
        "USER": "tianhaowu",
        "THRIFT_TLS_CL_CERT_PATH": "/tmp/test-cert",
        "THRIFT_TLS_CL_KEY_PATH": "/tmp/test-key",
        "X2P_ENV": "test-environment",
        "X2P_CFG_ENV": "test-config",
        launch.SELF_SHA_ENV: "a" * 64,
        launch.AUTHORIZATION_SHA_ENV: "b" * 64,
        **{name: "c" * 64 for name in launch.METADATA_HASH_ENV.values()},
    }
    monkeypatch.setattr(launch.os, "environ", environment)
    monkeypatch.setattr(launch, "SYSTEM_PYTHON", Path(sys.executable).resolve(strict=True))
    monkeypatch.chdir("/storage/home/tianhaowu")
    self_sha, authorization_sha, metadata = launch.validate_environment()
    assert (self_sha, authorization_sha) == ("a" * 64, "b" * 64)
    assert set(metadata) == set(launch.METADATA_HASH_ENV)
    environment["X2P_PROXY_URL"] = "must-not-be-ambient"
    with pytest.raises(RuntimeError, match="environment"):
        launch.validate_environment()


def test_launch_canonicalizes_tls_paths(launch: Any, tmp_path: Path) -> None:
    certificate = tmp_path / "certificate"
    key = tmp_path / "key"
    certificate.write_text("test")
    key.write_text("test")
    certificate_link = tmp_path / "certificate-link"
    key_link = tmp_path / "key-link"
    certificate_link.symlink_to(certificate)
    key_link.symlink_to(key)
    environment = {
        "THRIFT_TLS_CL_CERT_PATH": str(certificate_link),
        "THRIFT_TLS_CL_KEY_PATH": str(key_link),
    }
    launch.canonicalize_tls(environment)
    assert environment == {
        "THRIFT_TLS_CL_CERT_PATH": str(certificate),
        "THRIFT_TLS_CL_KEY_PATH": str(key),
    }


def test_launch_audit_runs_every_launcher_gate(launch: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    checked_paths: dict[str, Path] = {}

    def validate_authorization(_authorization: object, **paths: Path) -> dict[str, str]:
        calls.append("authorization")
        checked_paths.update(paths)
        return {"job_name": f"vmvm-owner-v4-{TOKEN}"}

    fake_launcher = SimpleNamespace(
        UTC=__import__("datetime").UTC,
        datetime=__import__("datetime").datetime,
        _ensure_absent=lambda: calls.append("filesystem"),
        _name_absent=lambda _name, _date: calls.append("scheduler_name") or True,
        _validate_outer_environment=lambda: calls.append("outer_environment"),
        load_authorization=lambda _path, _sha: calls.append("authorization_file") or ({}, b"{}", "d" * 64),
        validate_authorization=validate_authorization,
        validate_source=lambda: calls.append("source"),
    )
    launcher = Path("/checkpoint/example/launch_vmvm_owner_lifecycle_v4.py")
    authorization = Path("/checkpoint/example/authorization.json")
    monkeypatch.setattr(launch, "LAUNCHER", launcher)
    monkeypatch.setattr(launch, "AUTHORIZATION", authorization)
    launch.audit_launcher(fake_launcher, "d" * 64)
    assert calls == [
        "outer_environment",
        "authorization_file",
        "authorization",
        "source",
        "filesystem",
        "scheduler_name",
    ]
    assert checked_paths == {
        "launcher": launcher,
        "wrapper": launcher.parent / "run_vmvm_owner_lifecycle_v4.sbatch",
        "probe": launcher.parent / "probe_vmvm_owner_lifecycle_v4.py",
        "finalizer": launcher.parent / "finalize_vmvm_owner_lifecycle_v4.py",
    }


def test_one_shot_launch_keeps_proxy_out_of_argv_and_scrubs_control_environment(
    launch: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata = {label: character * 64 for (label, _name), character in zip(launch.METADATA_HASH_ENV.items(), "cdef")}
    environment = {
        "THRIFT_TLS_CL_CERT_PATH": "/canonical/cert",
        "THRIFT_TLS_CL_KEY_PATH": "/canonical/key",
        "X2P_ENV": "test-environment",
        "X2P_CFG_ENV": "test-config",
        launch.SELF_SHA_ENV: "a" * 64,
        launch.AUTHORIZATION_SHA_ENV: "b" * 64,
        **{environment_name: metadata[label] for label, environment_name in launch.METADATA_HASH_ENV.items()},
    }
    self_path = Path(launch.__file__).resolve(strict=True)
    launcher_path = Path("/checkpoint/example/launch_vmvm_owner_lifecycle_v4.py")
    authorization_path = Path("/checkpoint/example/authorization.json")
    proxy = "test-only-proxy"
    calls: list[object] = []

    class FakeRecovery:
        METADATA_HASH_ENV = launch.METADATA_HASH_ENV

        @staticmethod
        def recover_proxy(received: dict[str, str]) -> str:
            calls.append(("recover", received))
            return proxy

    def fake_stable_file(path: Path, **_kwargs: object) -> bytes:
        if path == launcher_path:
            return b"exact launcher bytes"
        return b"validated"

    def fake_audit(_launcher: object, authorization_sha: str) -> None:
        calls.append(("audit", authorization_sha, dict(launch.os.environ), tuple(launch.sys.argv)))

    monkeypatch.setattr(launch.os, "environ", environment)
    monkeypatch.setattr(launch.sys, "argv", [str(self_path), "audit"])
    monkeypatch.setattr(launch, "SELF_PATH", self_path)
    monkeypatch.setattr(launch, "LAUNCHER", launcher_path)
    monkeypatch.setattr(launch, "AUTHORIZATION", authorization_path)
    monkeypatch.setattr(launch, "install_signal_handlers", lambda: None)
    monkeypatch.setattr(launch, "validate_environment", lambda: ("a" * 64, "b" * 64, metadata))
    monkeypatch.setattr(launch, "stable_file", fake_stable_file)
    monkeypatch.setattr(launch, "stable_recovery_module", lambda: FakeRecovery)
    monkeypatch.setattr(launch, "stable_launcher_module", lambda raw: calls.append(("compile", raw)) or object())
    monkeypatch.setattr(launch, "canonicalize_tls", lambda _environment: calls.append("canonical_tls"))
    monkeypatch.setattr(launch, "audit_launcher", fake_audit)
    monkeypatch.setattr(
        launch, "emit_bounded", lambda descriptor, payload: calls.append(("output", descriptor, payload))
    )
    monkeypatch.setattr(launch.signal, "pthread_sigmask", lambda _operation, _signals: set())
    monkeypatch.setattr(launch.signal, "signal", lambda _signum, _handler: None)
    assert launch.main() == 0
    audit = next(call for call in calls if isinstance(call, tuple) and call[0] == "audit")
    child_environment = audit[2]
    arguments = audit[3]
    assert child_environment["X2P_PROXY_URL"] == proxy
    assert child_environment["APPROVED_DIAGNOSTIC_LAUNCHER_SHA256"] == launch.LAUNCHER_SHA256
    assert launch.SELF_SHA_ENV not in child_environment
    assert launch.AUTHORIZATION_SHA_ENV not in child_environment
    assert not set(launch.METADATA_HASH_ENV.values()) & set(child_environment)
    assert proxy not in arguments
    assert ("compile", b"exact launcher bytes") in calls
    assert "canonical_tls" in calls
    assert "X2P_PROXY_URL" not in launch.os.environ


@pytest.mark.parametrize("fixture_name", ("recovery", "launch"))
def test_pending_signal_at_handler_unmask_is_caught_and_terminalized_once(
    fixture_name: str,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = request.getfixturevalue(fixture_name)
    handlers: dict[signal.Signals, object] = {}
    outputs: list[tuple[int, bytes]] = []
    restores = 0

    def fake_signal(signum: signal.Signals, handler: object) -> None:
        handlers[signum] = handler

    def fake_mask(operation: int, _mask: set[signal.Signals]) -> set[signal.Signals]:
        nonlocal restores
        if operation == signal.SIG_SETMASK:
            restores += 1
            if restores == 1:
                handler = handlers[signal.SIGTERM]
                assert callable(handler)
                handler(signal.SIGTERM, None)
        return set()

    monkeypatch.setattr(module.signal, "signal", fake_signal)
    monkeypatch.setattr(module.signal, "pthread_sigmask", fake_mask)
    monkeypatch.setattr(module, "emit_bounded", lambda descriptor, payload: outputs.append((descriptor, payload)))
    monkeypatch.setattr(module.os, "environ", {})
    monkeypatch.setattr(module.sys, "argv", [str(module.__file__), "audit"])
    monkeypatch.setattr(module, "INTERRUPTED", False)
    assert module.main() == 2
    assert outputs == [(2, module.FAILURE_OUTPUT)]
    assert restores == 2


@pytest.mark.parametrize("fixture_name", ("recovery", "launch"))
def test_signal_after_success_write_cannot_emit_second_record(
    fixture_name: str,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = request.getfixturevalue(fixture_name)
    handlers: dict[signal.Signals, object] = {signum: module.signal_handler for signum in module.HANDLED_SIGNALS}
    outputs: list[bytes] = []
    environment = {
        "X2P_PROXY_URL": "test-only-proxy",
        module.SELF_SHA_ENV: "a" * 64,
        **{name: "b" * 64 for name in module.METADATA_HASH_ENV.values()},
    }
    if fixture_name == "launch":
        environment[module.AUTHORIZATION_SHA_ENV] = "c" * 64

    def fake_signal(signum: signal.Signals, handler: object) -> None:
        handlers[signum] = handler

    def fake_write(_descriptor: int, payload: bytes) -> int:
        outputs.append(payload)
        handler = handlers[signal.SIGTERM]
        if callable(handler):
            handler(signal.SIGTERM, None)
        else:
            assert handler == signal.SIG_IGN
        return len(payload)

    monkeypatch.setattr(module.signal, "signal", fake_signal)
    monkeypatch.setattr(module.signal, "pthread_sigmask", lambda _operation, _signals: set())
    monkeypatch.setattr(module.os, "write", fake_write)
    monkeypatch.setattr(module.os, "environ", environment)
    secret_state: dict[str, str | None] = {"proxy": "test-only-proxy"}
    assert module.terminalize(1, module.SUCCESS_OUTPUT, 0, secret_state) == 0
    assert outputs == [module.SUCCESS_OUTPUT]
    assert secret_state == {"proxy": None}
    assert "X2P_PROXY_URL" not in environment
    assert module.SELF_SHA_ENV not in environment
    assert not set(module.METADATA_HASH_ENV.values()) & set(environment)


@pytest.mark.parametrize("fixture_name", ("recovery", "launch"))
def test_signal_immediately_before_terminal_mask_cannot_escape_or_skip_scrub(
    fixture_name: str,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = request.getfixturevalue(fixture_name)
    outputs: list[bytes] = []
    injected = False
    environment = {
        "X2P_PROXY_URL": "test-only-proxy",
        module.SELF_SHA_ENV: "a" * 64,
        **{name: "b" * 64 for name in module.METADATA_HASH_ENV.values()},
    }
    if fixture_name == "launch":
        environment[module.AUTHORIZATION_SHA_ENV] = "c" * 64

    def inject_before_block(operation: int, _mask: set[signal.Signals]) -> set[signal.Signals]:
        nonlocal injected
        if operation == signal.SIG_BLOCK and not injected:
            injected = True
            module.signal_handler(signal.SIGTERM, None)
        return set()

    monkeypatch.setattr(module.signal, "pthread_sigmask", inject_before_block)
    monkeypatch.setattr(module.signal, "signal", lambda _signum, _handler: None)
    monkeypatch.setattr(module.os, "write", lambda _descriptor, payload: outputs.append(payload) or len(payload))
    monkeypatch.setattr(module.os, "environ", environment)
    monkeypatch.setattr(module, "TERMINAL_LATCHED", True)
    secret_state: dict[str, str | None] = {"proxy": "test-only-proxy"}
    assert module.terminalize(1, module.SUCCESS_OUTPUT, 0, secret_state) == 0
    assert injected
    assert outputs == [module.SUCCESS_OUTPUT]
    assert secret_state == {"proxy": None}
    assert "X2P_PROXY_URL" not in environment


def test_launch_commit_latch_precedes_signal_delivery(launch: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeLauncher:
        def __init__(self) -> None:
            self._publish_success = self.publish_success

        @staticmethod
        def publish_success(*_args: object, **kwargs: object) -> str:
            kwargs["commit_state"]["committed"] = True
            return "receipt"

        def launch(self, _authorization: Path, _authorization_sha: str) -> dict[str, object]:
            commit_state = {"committed": False}
            self._publish_success(commit_state=commit_state)
            assert launch.SUBMISSION_COMMITTED
            launch.signal_handler(signal.SIGTERM, None)
            return {"state": "submitted", "submission_attempts": 1}

    monkeypatch.setattr(launch.signal, "pthread_sigmask", lambda _operation, _signals: set())
    monkeypatch.setattr(launch, "INTERRUPTED", False)
    monkeypatch.setattr(launch, "SUBMISSION_COMMITTED", False)
    monkeypatch.setattr(launch, "TERMINAL_LATCHED", False)
    fake = FakeLauncher()
    assert launch.launch_with_commit_latch(fake, "a" * 64) == {
        "state": "submitted",
        "submission_attempts": 1,
    }
    assert launch.SUBMISSION_COMMITTED
    assert launch.TERMINAL_LATCHED
    assert fake._publish_success == fake.publish_success


def test_committed_launch_interrupt_before_success_assignment_reports_submitted_once(
    launch: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata = {label: character * 64 for (label, _name), character in zip(launch.METADATA_HASH_ENV.items(), "cdef")}
    environment = {
        "THRIFT_TLS_CL_CERT_PATH": "/canonical/cert",
        "THRIFT_TLS_CL_KEY_PATH": "/canonical/key",
        "X2P_ENV": "test-environment",
        "X2P_CFG_ENV": "test-config",
        launch.SELF_SHA_ENV: "a" * 64,
        launch.AUTHORIZATION_SHA_ENV: "b" * 64,
        **{environment_name: metadata[label] for label, environment_name in launch.METADATA_HASH_ENV.items()},
    }
    self_path = Path(launch.__file__).resolve(strict=True)
    launcher_path = Path("/checkpoint/example/launch_vmvm_owner_lifecycle_v4.py")
    outputs: list[tuple[int, bytes]] = []

    class FakeRecovery:
        METADATA_HASH_ENV = launch.METADATA_HASH_ENV

        @staticmethod
        def recover_proxy(_received: dict[str, str]) -> str:
            return "test-only-proxy"

    fake_launcher = SimpleNamespace(_validate_outer_environment=lambda: None)

    def committed_then_interrupted(_launcher: object, _authorization_sha: str) -> dict[str, object]:
        launch.SUBMISSION_COMMITTED = True
        launch.TERMINAL_LATCHED = True
        raise launch.LaunchRecoveryInterrupted

    monkeypatch.setattr(launch.os, "environ", environment)
    monkeypatch.setattr(launch.sys, "argv", [str(self_path), "execute"])
    monkeypatch.setattr(launch, "SELF_PATH", self_path)
    monkeypatch.setattr(launch, "LAUNCHER", launcher_path)
    monkeypatch.setattr(launch, "install_signal_handlers", lambda: None)
    monkeypatch.setattr(launch, "validate_environment", lambda: ("a" * 64, "b" * 64, metadata))
    monkeypatch.setattr(
        launch,
        "stable_file",
        lambda path, **_kwargs: b"exact launcher bytes" if path == launcher_path else b"validated",
    )
    monkeypatch.setattr(launch, "stable_recovery_module", lambda: FakeRecovery)
    monkeypatch.setattr(launch, "stable_launcher_module", lambda _raw: fake_launcher)
    monkeypatch.setattr(launch, "canonicalize_tls", lambda _environment: None)
    monkeypatch.setattr(launch, "launch_with_commit_latch", committed_then_interrupted)
    monkeypatch.setattr(launch.signal, "pthread_sigmask", lambda _operation, _signals: set())
    monkeypatch.setattr(launch.signal, "signal", lambda _signum, _handler: None)
    monkeypatch.setattr(launch, "emit_bounded", lambda descriptor, payload: outputs.append((descriptor, payload)))
    assert launch.main() == 0
    assert outputs == [(1, launch.SUBMISSION_OUTPUT)]
    assert "X2P_PROXY_URL" not in launch.os.environ


@pytest.mark.parametrize("fixture_name", ("creator", "recovery", "launch"))
def test_public_output_is_fixed_canonical_and_bounded(
    fixture_name: str,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = request.getfixturevalue(fixture_name)
    writes: list[tuple[int, bytes]] = []
    monkeypatch.setattr(
        module.os, "write", lambda descriptor, payload: writes.append((descriptor, payload)) or len(payload)
    )
    payloads = [module.SUCCESS_OUTPUT, module.FAILURE_OUTPUT]
    if fixture_name == "launch":
        payloads.append(module.SUBMISSION_OUTPUT)
    for payload in payloads:
        assert len(payload) <= 256
        assert payload.endswith(b"\n")
        assert payload.count(b"\n") == 1
        assert json.dumps(json.loads(payload), sort_keys=True, separators=(",", ":")).encode() + b"\n" == payload
        module.emit_bounded(1, payload)
    assert writes == [(1, payload) for payload in payloads]
    with pytest.raises(RuntimeError, match="output_contract"):
        module.emit_bounded(1, b"x" * 256 + b"\n")
    with pytest.raises(RuntimeError, match="output_contract"):
        module.emit_bounded(1, b"{}\n{}\n")


def test_candidates_do_not_embed_credential_values() -> None:
    combined = b"\n".join(path.read_bytes() for path in (CREATOR_PATH, RECOVERY_PATH, LAUNCH_PATH, INVOCATION_PATH))
    assert b"X2P_PROXY_URL=" not in combined
    assert b"BEGIN CERTIFICATE" not in combined
    assert b"PRIVATE KEY" not in combined


def test_readme_requires_retained_fd_invocation() -> None:
    readme = (HERE / "README.md").read_text()
    for required in (
        "only proposed operator-facing entrypoint",
        "opened with `O_NOFOLLOW`",
        "remain open across the entire child lifetime",
        "`/usr/bin/python3.12 -I -S -B /proc/self/fd/<fd> <mode>`",
        "Direct pathname invocation of the envelope or any helper is forbidden",
    ):
        assert required in readme


def invocation_outer_environment() -> dict[str, str]:
    return {
        "TMUX": "/tmp/test-tmux,1,0",
        "TMUX_PANE": "%0",
        "THRIFT_TLS_CL_CERT_PATH": "/test/tls-certificate",
        "THRIFT_TLS_CL_KEY_PATH": "/test/tls-key",
        "X2P_ENV": "test-environment",
        "X2P_CFG_ENV": "test-configuration",
        "X2P_PROXY_URL": "must-not-be-forwarded",
        "UNRELATED_SECRET": "must-not-be-forwarded",
        "PATH": "/ambient/path",
    }


def test_invocation_binds_exact_control_chain_without_private_v2_hashes(invocation: Any) -> None:
    assert invocation.CONTROL_FILES == {
        "creator": (invocation.BASE / "diagnostics" / CREATOR_PATH.name, digest(CREATOR_PATH)),
        "create": (invocation.BASE / "diagnostics" / RECOVERY_PATH.name, digest(RECOVERY_PATH)),
        "launch": (invocation.BASE / "diagnostics" / LAUNCH_PATH.name, digest(LAUNCH_PATH)),
    }
    source = INVOCATION_PATH.read_text()
    for forbidden in (
        "AUTHORIZATION_V2_SHA256 =",
        "FAILURE_V2_SHA256 =",
        "RECEIPT_V2_SHA256 =",
        "ENVIRONMENT_V2_SHA256 =",
    ):
        assert forbidden not in source
    assert set(invocation.LINEAGE_FILES) == set(invocation.METADATA_HASH_ENV)


def test_invocation_builds_exact_clean_child_environment(
    invocation: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(invocation, "OWNER_UID", os.getuid())
    monkeypatch.setattr(invocation, "WORKING_DIRECTORY", tmp_path)
    monkeypatch.setattr(invocation, "SYSTEM_PYTHON", Path(sys.executable).resolve(strict=True))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        invocation.sys,
        "flags",
        SimpleNamespace(isolated=1, no_site=1, dont_write_bytecode=1),
    )
    child = invocation.build_child_environment(invocation_outer_environment())
    assert child == {
        "HOME": str(tmp_path),
        "LANG": "C",
        "LC_ALL": "C",
        "LOGNAME": "tianhaowu",
        "PATH": "/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "TMUX": "/tmp/test-tmux,1,0",
        "TMUX_PANE": "%0",
        "TZ": "UTC",
        "USER": "tianhaowu",
        "THRIFT_TLS_CL_CERT_PATH": "/test/tls-certificate",
        "THRIFT_TLS_CL_KEY_PATH": "/test/tls-key",
        "X2P_ENV": "test-environment",
        "X2P_CFG_ENV": "test-configuration",
    }
    assert "X2P_PROXY_URL" not in child
    assert "UNRELATED_SECRET" not in child

    exact_child = dict(child)
    exact_child[invocation.HELPER_SHA_ENV["create"]] = invocation.CONTROL_FILES["create"][1]
    exact_child.update({name: "a" * 64 for name in invocation.METADATA_HASH_ENV.values()})
    invocation.validate_child_environment("create", exact_child)
    for name, value in (
        ("X2P_PROXY_URL", "not-allowed"),
        (invocation.HELPER_SHA_ENV["create"], "b" * 64),
    ):
        invalid_child = dict(exact_child)
        invalid_child[name] = value
        with pytest.raises(RuntimeError, match="child_environment"):
            invocation.validate_child_environment("create", invalid_child)

    for name, value in (
        ("TMUX_PANE", "%1"),
        ("X2P_ENV", ""),
        ("X2P_CFG_ENV", "bad\nvalue"),
        ("THRIFT_TLS_CL_CERT_PATH", "relative"),
    ):
        invalid = invocation_outer_environment()
        invalid[name] = value
        with pytest.raises(RuntimeError):
            invocation.build_child_environment(invalid)


def test_invocation_self_requires_exact_retained_descriptor(
    invocation: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "installed-envelope.py"
    raw = b"reviewed envelope bytes\n"
    source.write_bytes(raw)
    source.chmod(0o500)
    descriptor = os.open(source, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        proc_path = f"/proc/self/fd/{descriptor}"
        monkeypatch.setattr(invocation, "OWNER_UID", os.getuid())
        monkeypatch.setattr(invocation, "SELF_PATH", source)
        monkeypatch.setattr(invocation, "__file__", proc_path)
        monkeypatch.setattr(invocation.sys, "argv", [proc_path, "create", "audit"])
        invocation.validate_self_invocation(hashlib.sha256(raw).hexdigest())

        replacement = tmp_path / "replacement"
        source.rename(replacement)
        source.write_bytes(raw)
        source.chmod(0o500)
        with pytest.raises(RuntimeError, match="self_identity"):
            invocation.validate_self_invocation(hashlib.sha256(raw).hexdigest())
    finally:
        os.close(descriptor)


def test_invocation_stable_hash_rejects_symlink_hardlink_and_replacement(
    invocation: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(invocation, "OWNER_UID", os.getuid())
    regular = tmp_path / "regular"
    regular.write_bytes(b"bound bytes")
    regular.chmod(0o400)
    expected = hashlib.sha256(regular.read_bytes()).hexdigest()
    assert invocation.stable_hash(regular, mode=0o400, expected_sha256=expected) == expected

    symlink = tmp_path / "symlink"
    symlink.symlink_to(regular)
    with pytest.raises(OSError):
        invocation.stable_hash(symlink, mode=0o400)

    hardlink = tmp_path / "hardlink"
    os.link(regular, hardlink)
    with pytest.raises(RuntimeError, match="file_identity"):
        invocation.stable_hash(regular, mode=0o400)
    hardlink.unlink()

    original_hash = invocation.read_descriptor_hash
    old = tmp_path / "old"
    swapped = False

    def replace_after_read(descriptor: int, maximum: int) -> tuple[str, int]:
        nonlocal swapped
        result = original_hash(descriptor, maximum)
        if not swapped:
            swapped = True
            regular.rename(old)
            regular.write_bytes(b"replacement")
            regular.chmod(0o400)
        return result

    monkeypatch.setattr(invocation, "read_descriptor_hash", replace_after_read)
    with pytest.raises(RuntimeError, match="file_identity"):
        invocation.stable_hash(regular, mode=0o400, expected_sha256=expected)


@pytest.mark.parametrize("target", ("create", "launch"))
def test_invocation_computes_lineage_and_authorization_hashes_internally(
    target: str,
    invocation: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Path, int, str | None]] = []

    def fake_stable_hash(path: Path, *, mode: int, expected_sha256: str | None = None) -> str:
        calls.append((path, mode, expected_sha256))
        return hashlib.sha256(str(path).encode()).hexdigest()

    helper_path, helper_hash = invocation.CONTROL_FILES[target]
    bound = invocation.BoundFile(91, 92, helper_path, (1,), helper_hash)
    monkeypatch.setattr(invocation, "stable_hash", fake_stable_hash)
    monkeypatch.setattr(invocation, "open_bound_file", lambda *_args, **_kwargs: bound)
    environment: dict[str, str] = {}
    observed_bound, child = invocation.prepare_invocation(target, environment)
    assert observed_bound == bound
    assert child[invocation.HELPER_SHA_ENV[target]] == helper_hash
    for label, path in invocation.LINEAGE_FILES.items():
        assert child[invocation.METADATA_HASH_ENV[label]] == hashlib.sha256(str(path).encode()).hexdigest()
        assert (path, 0o400, None) in calls
    for label, (path, expected) in invocation.CONTROL_FILES.items():
        if label != target:
            assert (path, 0o500, expected) in calls
    if target == "launch":
        assert (
            child[invocation.AUTHORIZATION_SHA_ENV]
            == hashlib.sha256(str(invocation.AUTHORIZATION_V4).encode()).hexdigest()
        )
        assert (invocation.AUTHORIZATION_V4, 0o400, None) in calls
    else:
        assert invocation.AUTHORIZATION_SHA_ENV not in child
        assert all(path != invocation.AUTHORIZATION_V4 for path, _mode, _expected in calls)


def test_invocation_rejects_helper_name_replacement_before_spawn(
    invocation: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    helper = tmp_path / "helper.py"
    raw = b"reviewed helper\n"
    helper.write_bytes(raw)
    helper.chmod(0o500)
    monkeypatch.setattr(invocation, "OWNER_UID", os.getuid())
    bound = invocation.open_bound_file(
        helper,
        mode=0o500,
        expected_sha256=hashlib.sha256(raw).hexdigest(),
    )
    original = tmp_path / "original"
    helper.rename(original)
    helper.write_bytes(raw)
    helper.chmod(0o500)
    monkeypatch.setattr(invocation, "validate_child_environment", lambda _target, _environment: None)
    try:
        with pytest.raises(RuntimeError, match="file_identity"):
            invocation.invoke_helper(
                bound,
                target="create",
                mode="audit",
                environment={"PATH": "/usr/bin:/bin"},
            )
    finally:
        invocation.close_bound_file(bound)


def test_invocation_executes_exact_fd_and_retains_it_until_child_exit(
    invocation: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    expected = invocation.EXPECTED_CHILD_OUTPUT[("create", "audit")]
    helper = tmp_path / "helper.py"
    helper.write_text(
        f"import os\nfrom pathlib import Path\nfd = int(Path(__file__).name)\nos.fstat(fd)\nos.write(1, {expected!r})\n"
    )
    helper.chmod(0o500)
    raw = helper.read_bytes()
    monkeypatch.setattr(invocation, "OWNER_UID", os.getuid())
    monkeypatch.setattr(invocation, "SYSTEM_PYTHON", Path(sys.executable).resolve(strict=True))
    monkeypatch.setattr(invocation, "WORKING_DIRECTORY", tmp_path)
    monkeypatch.setattr(invocation, "CHILD_TIMEOUT_SECONDS", 10)
    monkeypatch.setattr(invocation, "CHILD_TERM_GRACE_SECONDS", 2)
    monkeypatch.setattr(invocation, "CHILD_KILL_GRACE_SECONDS", 2)
    monkeypatch.setattr(invocation, "INTERRUPTED", False)
    monkeypatch.setattr(invocation, "validate_child_environment", lambda _target, _environment: None)
    bound = invocation.open_bound_file(
        helper,
        mode=0o500,
        expected_sha256=hashlib.sha256(raw).hexdigest(),
    )
    try:
        returncode, stdout, stderr = invocation.invoke_helper(
            bound,
            target="create",
            mode="audit",
            environment={"PATH": "/usr/bin:/bin"},
        )
        assert (returncode, stdout, stderr) == (0, expected, b"")
        os.fstat(bound.descriptor)
    finally:
        invocation.close_bound_file(bound)
    with pytest.raises(OSError):
        os.fstat(bound.descriptor)


def test_invocation_child_argv_and_environment_never_mix_private_values(
    invocation: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    helper = tmp_path / "helper.py"
    helper.write_bytes(b"reviewed helper\n")
    helper.chmod(0o500)
    monkeypatch.setattr(invocation, "OWNER_UID", os.getuid())
    bound = invocation.open_bound_file(helper, mode=0o500)
    captured: dict[str, object] = {}
    private_values = {
        "HOME": str(invocation.WORKING_DIRECTORY),
        "LANG": "C",
        "LC_ALL": "C",
        "LOGNAME": "tianhaowu",
        "PATH": "/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "TMUX": "/tmp/private-tmux,1,0",
        "TMUX_PANE": "%0",
        "TZ": "UTC",
        "USER": "tianhaowu",
        "THRIFT_TLS_CL_CERT_PATH": "/private/certificate",
        "THRIFT_TLS_CL_KEY_PATH": "/private/key",
        "X2P_ENV": "private-environment",
        "X2P_CFG_ENV": "private-configuration",
        invocation.HELPER_SHA_ENV["create"]: invocation.CONTROL_FILES["create"][1],
        **{name: "a" * 64 for name in invocation.METADATA_HASH_ENV.values()},
    }

    class FakeProcess:
        pid = 123456
        returncode = 0

        @staticmethod
        def poll() -> int:
            return 0

        @staticmethod
        def communicate(*, timeout: float) -> tuple[bytes, bytes]:
            assert timeout > 0
            os.fstat(bound.descriptor)
            return invocation.EXPECTED_CHILD_OUTPUT[("create", "audit")], b""

    def fake_popen(arguments: list[str], **kwargs: object) -> FakeProcess:
        captured["arguments"] = tuple(arguments)
        captured.update(kwargs)
        return FakeProcess()

    monkeypatch.setattr(invocation.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(invocation, "process_start_ticks", lambda _pid: 7)
    monkeypatch.setattr(invocation, "same_process", lambda _pid, _ticks: False)
    monkeypatch.setattr(invocation.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(invocation, "group_exists", lambda _group: False)
    monkeypatch.setattr(invocation.signal, "pthread_sigmask", lambda _operation, _signals: set())
    monkeypatch.setattr(invocation, "INTERRUPTED", False)
    try:
        result = invocation.invoke_helper(
            bound,
            target="create",
            mode="audit",
            environment=private_values,
        )
        assert result == (0, invocation.EXPECTED_CHILD_OUTPUT[("create", "audit")], b"")
        assert captured["arguments"] == (
            str(invocation.SYSTEM_PYTHON),
            "-I",
            "-S",
            "-B",
            f"/proc/self/fd/{bound.descriptor}",
            "audit",
        )
        assert captured["pass_fds"] == (bound.descriptor,)
        assert captured["close_fds"] is True
        assert captured["start_new_session"] is True
        assert captured["env"] == private_values
        flattened_arguments = "\0".join(captured["arguments"])
        private_names = {
            "TMUX",
            "THRIFT_TLS_CL_CERT_PATH",
            "THRIFT_TLS_CL_KEY_PATH",
            "X2P_ENV",
            "X2P_CFG_ENV",
            invocation.HELPER_SHA_ENV["create"],
            *invocation.METADATA_HASH_ENV.values(),
        }
        assert all(private_values[name] not in flattened_arguments for name in private_names)
        os.fstat(bound.descriptor)
    finally:
        invocation.close_bound_file(bound)


def test_invocation_forwards_signal_and_preserves_exact_child_outcome(
    invocation: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bound = invocation.BoundFile(91, 92, Path("/fixed/helper"), (1,), "a" * 64)
    forwarded: list[int] = []

    class FakeProcess:
        pid = 123456
        returncode: int | None = None
        calls = 0

        @staticmethod
        def poll() -> int | None:
            return FakeProcess.returncode

        @staticmethod
        def communicate(*, timeout: float) -> tuple[bytes, bytes]:
            assert timeout > 0
            FakeProcess.calls += 1
            if FakeProcess.calls == 1:
                invocation.INTERRUPTED = True
                invocation.INTERRUPT_SIGNAL = signal.SIGTERM
                raise subprocess.TimeoutExpired("helper", timeout)
            FakeProcess.returncode = 0
            return invocation.EXPECTED_CHILD_OUTPUT[("launch", "execute")], b""

    monkeypatch.setattr(invocation, "validate_child_environment", lambda _target, _environment: None)
    monkeypatch.setattr(invocation, "verify_bound_name", lambda _bound: None)
    monkeypatch.setattr(invocation.subprocess, "Popen", lambda *_args, **_kwargs: FakeProcess())
    monkeypatch.setattr(invocation, "process_start_ticks", lambda _pid: 7)
    monkeypatch.setattr(invocation, "same_process", lambda _pid, _ticks: False)
    monkeypatch.setattr(invocation.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(invocation, "group_exists", lambda _group: False)
    monkeypatch.setattr(
        invocation,
        "signal_child_group",
        lambda _process, _group, _ticks, signum: forwarded.append(signum),
    )
    monkeypatch.setattr(invocation.signal, "pthread_sigmask", lambda _operation, _signals: set())
    monkeypatch.setattr(invocation, "INTERRUPTED", False)
    monkeypatch.setattr(invocation, "INTERRUPT_SIGNAL", None)
    monkeypatch.setattr(invocation, "TERMINAL_LATCHED", False)
    monkeypatch.setattr(invocation, "CHILD_OUTCOME", None)
    result = invocation.invoke_helper(
        bound,
        target="launch",
        mode="execute",
        environment={},
    )
    assert result == (0, invocation.EXPECTED_CHILD_OUTPUT[("launch", "execute")], b"")
    assert forwarded == [signal.SIGTERM]
    assert invocation.CHILD_OUTCOME == ("launch", "execute")
    assert invocation.TERMINAL_LATCHED


def test_invocation_reaps_child_when_spawn_identity_binding_fails(
    invocation: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bound = invocation.BoundFile(91, 92, Path("/fixed/helper"), (1,), "a" * 64)
    reaped: list[object] = []

    class FakeProcess:
        pid = 123456

    process = FakeProcess()
    monkeypatch.setattr(invocation, "validate_child_environment", lambda _target, _environment: None)
    monkeypatch.setattr(invocation, "verify_bound_name", lambda _bound: None)
    monkeypatch.setattr(invocation.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(
        invocation,
        "process_start_ticks",
        lambda _pid: (_ for _ in ()).throw(RuntimeError("identity")),
    )
    monkeypatch.setattr(invocation, "reap_spawn_failure", lambda observed: reaped.append(observed))
    monkeypatch.setattr(invocation.signal, "pthread_sigmask", lambda _operation, _signals: set())
    monkeypatch.setattr(invocation, "INTERRUPTED", False)
    with pytest.raises(RuntimeError, match="identity"):
        invocation.invoke_helper(bound, target="create", mode="audit", environment={})
    assert reaped == [process]


def test_invocation_signal_tolerates_bound_child_exit_race(
    invocation: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    polls = iter((None, 0))

    class ExitingProcess:
        pid = 123456

        @staticmethod
        def poll() -> int | None:
            return next(polls)

    monkeypatch.setattr(invocation, "same_process", lambda _pid, _ticks: False)
    monkeypatch.setattr(invocation, "group_exists", lambda _group: False)
    invocation.signal_child_group(ExitingProcess(), 123456, 7, signal.SIGTERM)


def test_invocation_never_relays_unexpected_child_output(
    invocation: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dummy = invocation.BoundFile(91, 92, Path("/fixed/helper"), (1,), "a" * 64)
    public: list[tuple[int, bytes]] = []
    environment = invocation_outer_environment()
    environment[invocation.SELF_SHA_ENV] = "b" * 64
    monkeypatch.setattr(invocation.os, "environ", environment)
    monkeypatch.setattr(invocation.sys, "argv", ["/proc/self/fd/9", "create", "audit"])
    monkeypatch.setattr(invocation, "install_signal_handlers", lambda: None)
    monkeypatch.setattr(invocation, "validate_self_invocation", lambda _expected: None)
    monkeypatch.setattr(invocation, "build_child_environment", lambda _environment: {"PRIVATE": "value"})
    monkeypatch.setattr(invocation, "prepare_invocation", lambda _target, child: (dummy, child))
    monkeypatch.setattr(invocation, "verify_bound_name", lambda _bound: None)
    monkeypatch.setattr(
        invocation,
        "invoke_helper",
        lambda *_args, **_kwargs: (0, b"unexpected-private-child-output\n", b""),
    )
    monkeypatch.setattr(invocation, "close_bound_file", lambda _bound: None)
    monkeypatch.setattr(invocation.signal, "pthread_sigmask", lambda _operation, _signals: set())
    monkeypatch.setattr(invocation.signal, "signal", lambda _signum, _handler: None)
    monkeypatch.setattr(
        invocation,
        "emit_bounded",
        lambda descriptor, payload: public.append((descriptor, payload)),
    )
    assert invocation.main() == 2
    assert public == [(2, invocation.FAILURE_OUTPUT)]
    assert b"unexpected-private-child-output" not in b"".join(payload for _descriptor, payload in public)
    assert not invocation.os.environ


def test_invocation_preserves_latched_child_outcome_across_late_cleanup_failure(
    invocation: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = "launch"
    mode = "execute"
    dummy = invocation.BoundFile(91, 92, Path("/fixed/helper"), (1,), "a" * 64)
    public: list[tuple[int, bytes]] = []
    environment = invocation_outer_environment()
    environment[invocation.SELF_SHA_ENV] = "b" * 64

    def committed_then_failed(*_args: object, **_kwargs: object) -> tuple[int, bytes, bytes]:
        invocation.CHILD_OUTCOME = (target, mode)
        invocation.TERMINAL_LATCHED = True
        raise RuntimeError("late_cleanup")

    monkeypatch.setattr(invocation.os, "environ", environment)
    monkeypatch.setattr(invocation.sys, "argv", ["/proc/self/fd/9", target, mode])
    monkeypatch.setattr(invocation, "install_signal_handlers", lambda: None)
    monkeypatch.setattr(invocation, "validate_self_invocation", lambda _expected: None)
    monkeypatch.setattr(invocation, "build_child_environment", lambda _environment: {"PRIVATE": "value"})
    monkeypatch.setattr(invocation, "prepare_invocation", lambda _target, child: (dummy, child))
    monkeypatch.setattr(invocation, "verify_bound_name", lambda _bound: None)
    monkeypatch.setattr(invocation, "invoke_helper", committed_then_failed)
    monkeypatch.setattr(
        invocation,
        "close_bound_file",
        lambda _bound: (_ for _ in ()).throw(RuntimeError("close")),
    )
    monkeypatch.setattr(invocation.signal, "pthread_sigmask", lambda _operation, _signals: set())
    monkeypatch.setattr(invocation.signal, "signal", lambda _signum, _handler: None)
    monkeypatch.setattr(
        invocation,
        "emit_bounded",
        lambda descriptor, payload: public.append((descriptor, payload)),
    )
    assert invocation.main() == 0
    assert public == [(1, invocation.SUCCESS_OUTPUT[(target, mode)])]
    assert not invocation.os.environ


@pytest.mark.parametrize("target", ("create", "launch"))
@pytest.mark.parametrize("mode", ("audit", "execute"))
def test_invocation_emits_one_fixed_success_after_exact_child_outcome(
    target: str,
    mode: str,
    invocation: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dummy = invocation.BoundFile(91, 92, Path("/fixed/helper"), (1,), "a" * 64)
    public: list[tuple[int, bytes]] = []
    environment = invocation_outer_environment()
    environment[invocation.SELF_SHA_ENV] = "b" * 64
    monkeypatch.setattr(invocation.os, "environ", environment)
    monkeypatch.setattr(invocation.sys, "argv", ["/proc/self/fd/9", target, mode])
    monkeypatch.setattr(invocation, "install_signal_handlers", lambda: None)
    monkeypatch.setattr(invocation, "validate_self_invocation", lambda _expected: None)
    monkeypatch.setattr(invocation, "build_child_environment", lambda _environment: {"PRIVATE": "value"})
    monkeypatch.setattr(invocation, "prepare_invocation", lambda _target, child: (dummy, child))
    monkeypatch.setattr(invocation, "verify_bound_name", lambda _bound: None)
    monkeypatch.setattr(
        invocation,
        "invoke_helper",
        lambda *_args, **_kwargs: (0, invocation.EXPECTED_CHILD_OUTPUT[(target, mode)], b""),
    )
    monkeypatch.setattr(invocation, "close_bound_file", lambda _bound: None)
    monkeypatch.setattr(invocation.signal, "pthread_sigmask", lambda _operation, _signals: set())
    monkeypatch.setattr(invocation.signal, "signal", lambda _signum, _handler: None)
    monkeypatch.setattr(
        invocation,
        "emit_bounded",
        lambda descriptor, payload: public.append((descriptor, payload)),
    )
    assert invocation.main() == 0
    assert public == [(1, invocation.SUCCESS_OUTPUT[(target, mode)])]
    assert not invocation.os.environ


def test_invocation_public_output_is_fixed_canonical_and_bounded(
    invocation: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writes: list[tuple[int, bytes]] = []
    monkeypatch.setattr(
        invocation.os,
        "write",
        lambda descriptor, payload: writes.append((descriptor, payload)) or len(payload),
    )
    for payload in (*invocation.SUCCESS_OUTPUT.values(), invocation.FAILURE_OUTPUT):
        assert len(payload) <= 256
        assert payload.endswith(b"\n")
        assert payload.count(b"\n") == 1
        assert json.dumps(json.loads(payload), sort_keys=True, separators=(",", ":")).encode() + b"\n" == payload
        invocation.emit_bounded(1, payload)
    assert writes == [(1, payload) for payload in (*invocation.SUCCESS_OUTPUT.values(), invocation.FAILURE_OUTPUT)]
    with pytest.raises(RuntimeError, match="output_contract"):
        invocation.emit_bounded(1, b"x" * 256 + b"\n")
    with pytest.raises(RuntimeError, match="output_contract"):
        invocation.emit_bounded(1, b"{}\n{}\n")
