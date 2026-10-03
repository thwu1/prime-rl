from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import signal
import stat
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
CREATOR = HERE / "create_k3_registry_pull_gate_v28_approval.py"
ENVELOPE = HERE / "run_k3_registry_pull_gate_v28_exact.sh"
GATE_CONTROLLER = HERE.parent / "kimi_registry_gate_v28_candidate/controller.py"
SUCCESS = b'{"kind":"k3-registry-pull-gate-v28-approval-create","state":"created"}\n'
FAILURE = b'{"category":"approval_create_failed","state":"blocked"}\n'


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_creator():
    return load_module(CREATOR, "k3_v28_creator_test")


def load_gate_controller():
    return load_module(GATE_CONTROLLER, "k3_v28_gate_controller_test")


def run_isolated(body: str) -> subprocess.CompletedProcess[bytes]:
    program = f"""
import importlib.util
import os
import signal
import sys
from pathlib import Path
p = Path({str(CREATOR)!r})
s = importlib.util.spec_from_file_location("creator_under_test", p)
m = importlib.util.module_from_spec(s)
assert s.loader is not None
sys.modules[s.name] = m
s.loader.exec_module(m)
{body}
"""
    return subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", program],
        capture_output=True,
        check=False,
    )


def envelope_bootstrap() -> str:
    text = ENVELOPE.read_text()
    prefix = "readonly bootstrap='"
    suffix = '\'\nexec /usr/bin/python3.12 -I -S -B -c "$bootstrap" "$mode"\n'
    assert text.count(prefix) == 1 and text.count(suffix) == 1
    return text.split(prefix, 1)[1].split(suffix, 1)[0]


def capture_bootstrap(
    tmp_path: Path, mode: str, environment: dict[str, str]
) -> tuple[subprocess.CompletedProcess[bytes], dict[str, object] | None]:
    capture = tmp_path / f"{mode}.json"
    harness = f"""
import json
import os
def capture_execve(path, argv, environment):
    with open({str(capture)!r}, "w", encoding="utf-8") as stream:
        json.dump({{"path":path,"argv":argv,"environment":environment}}, stream, sort_keys=True)
os.execve = capture_execve
"""
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", harness + envelope_bootstrap(), mode],
        env=environment,
        capture_output=True,
        check=False,
    )
    payload = json.loads(capture.read_text()) if capture.exists() else None
    return result, payload


def test_source_and_bundle_bindings_are_exact() -> None:
    creator = load_creator()
    controller = load_gate_controller()
    assert creator.GATE_SOURCE_COMMIT == "4d7b256fdce51a3d2a0dd7f336e18a927dd768ef"
    assert creator.GATE_SOURCE_TREE == "572b4bd1fd2db7deab150374398a9760a7ebf719"
    assert creator.GATE_SOURCE_SUBTREE == "8196764b93e052b4d897eb05cf1e98a123e2003a"
    assert creator.BUNDLE.name == "k3_registry_pull_gate_20260920t153000z_v28"
    assert creator.JOB_NAME == "k3-reg-pull-153000-v28"
    assert creator.COMMENT_PREFIX == "k3-reg-pull-v28:"
    assert len(creator.BUNDLE_HASHES) == 10
    assert set(creator.BUNDLE_HASHES) == set(creator.HASH_ENV)
    assert all(len(value) == 64 and int(value, 16) >= 0 for value in creator.BUNDLE_HASHES.values())
    assert {
        key: hashlib.sha256((GATE_CONTROLLER.parent / name).read_bytes()).hexdigest()
        for key, (name, _mode) in controller.BUNDLE_FILES.items()
    } == creator.BUNDLE_HASHES
    envelope = ENVELOPE.read_text()
    assert creator.GATE_SOURCE_COMMIT in envelope
    assert creator.GATE_SOURCE_TREE in envelope
    assert creator.GATE_SOURCE_SUBTREE in envelope


def test_corrected_unpinned_scheduler_contract_is_exact() -> None:
    creator = load_creator()
    controller = load_gate_controller()
    creator.validate_controller_contract(controller, dict(creator.BUNDLE_HASHES))
    scheduler = creator.SCHEDULER_CONTRACT
    assert "nodelist" not in scheduler
    assert scheduler["node_selection"] == "scheduler"
    assert scheduler["node_name_pattern"] == "g3-[0-9]{3}-[0-9]{3}"
    assert scheduler["partition"] == "g3"
    assert scheduler["qos"] == "g3_lowest"
    assert scheduler["account"] == "ram"
    assert scheduler["exclude"] == [
        "g3-136-221",
        "g3-136-247",
        "g3-136-251",
        "g3-136-253",
    ]
    command = controller.sbatch_command(Path("/private/environment.bin"), "a" * 24)
    assert not any(argument.startswith("--nodelist") for argument in command)
    assert command.count("--exclude=" + ",".join(scheduler["exclude"])) == 1


def test_creator_overwrites_exact_hash_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    creator = load_creator()
    monkeypatch.delenv("EXPECTED_APPROVAL_SHA256", raising=False)
    for name in creator.HASH_ENV.values():
        monkeypatch.setenv(name, "0" * 64)
    creator.install_hash_environment()
    assert {key: os.environ[name] for key, name in creator.HASH_ENV.items()} == creator.BUNDLE_HASHES
    monkeypatch.setenv("EXPECTED_APPROVAL_SHA256", "1" * 64)
    with pytest.raises(RuntimeError, match="approval_hash_injected"):
        creator.install_hash_environment()


def test_controller_load_requires_exact_regular_single_link_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    creator = load_creator()
    controller_path = tmp_path / "controller.py"
    raw = b"BOUND_VALUE = 7\n"
    controller_path.write_bytes(raw)
    controller_path.chmod(0o500)
    monkeypatch.setattr(creator, "CONTROLLER", controller_path)
    monkeypatch.setattr(creator, "CONTROLLER_SHA256", hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(creator, "OWNER_UID", os.getuid())
    assert creator.load_controller().BOUND_VALUE == 7
    monkeypatch.setattr(creator, "CONTROLLER_SHA256", "0" * 64)
    with pytest.raises(RuntimeError, match="controller_identity"):
        creator.load_controller()
    monkeypatch.setattr(creator, "CONTROLLER_SHA256", hashlib.sha256(raw).hexdigest())
    controller_path.chmod(0o400)
    with pytest.raises(RuntimeError, match="controller_identity"):
        creator.load_controller()


def test_publication_is_exclusive_and_stably_bound(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    creator = load_creator()
    assert "os.unlink" not in CREATOR.read_text()
    monkeypatch.setattr(creator, "OWNER_UID", os.getuid())
    target = tmp_path / "approval.json"
    raw = b'{"state":"approved"}\n'
    inode = creator.publish_exclusive(target, raw)
    info = target.stat(follow_symlinks=False)
    assert inode == (info.st_dev, info.st_ino)
    assert target.read_bytes() == raw
    assert stat.S_IMODE(info.st_mode) == 0o400
    assert info.st_uid == os.getuid() and info.st_nlink == 1
    with pytest.raises(FileExistsError):
        creator.publish_exclusive(target, raw)
    assert target.read_bytes() == raw


def test_signal_handler_raises_immediately() -> None:
    creator = load_creator()
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, set())
    try:
        with pytest.raises(creator.ApprovalInterrupted):
            creator.signal_handler(signal.SIGTERM, None)
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
    assert creator.INTERRUPTED is True


def test_success_emission_is_one_bounded_record() -> None:
    result = run_isolated("raise SystemExit(m.emit_result(True))")
    assert result.returncode == 0
    assert result.stdout == SUCCESS
    assert result.stderr == b""


@pytest.mark.parametrize("signum", [signal.SIGHUP, signal.SIGINT, signal.SIGTERM])
def test_pending_signal_forces_one_failure_record(signum: signal.Signals) -> None:
    result = run_isolated(
        f"""
signal.pthread_sigmask(signal.SIG_BLOCK, m.HANDLED_SIGNALS)
os.kill(os.getpid(), {int(signum)})
raise SystemExit(m.emit_result(True))
"""
    )
    assert result.returncode == 2
    assert result.stdout == b""
    assert result.stderr == FAILURE
    assert b"Traceback" not in result.stderr


def test_delivered_signal_has_one_failure_record_without_traceback() -> None:
    result = run_isolated(
        """
for signum in m.HANDLED_SIGNALS:
    signal.signal(signum, m.signal_handler)
try:
    os.kill(os.getpid(), signal.SIGTERM)
except m.ApprovalInterrupted:
    raise SystemExit(m.emit_result(False))
raise SystemExit(99)
"""
    )
    assert result.returncode == 2
    assert result.stdout == b""
    assert result.stderr == FAILURE
    assert b"Traceback" not in result.stderr


def test_signal_at_catch_to_emit_boundary_forces_one_failure_record() -> None:
    result = run_isolated(
        """
real_mask = m.signal.pthread_sigmask
calls = 0
def injecting_mask(how, mask):
    global calls
    calls += 1
    if calls == 1:
        raise m.ApprovalInterrupted
    return real_mask(how, mask)
m.signal.pthread_sigmask = injecting_mask
raise SystemExit(m.finish_result(True))
"""
    )
    assert result.returncode == 2
    assert result.stdout == b""
    assert result.stderr == FAILURE
    assert b"Traceback" not in result.stderr


def test_publication_closes_descriptors_before_pending_signal_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    creator = load_creator()
    monkeypatch.setattr(creator, "OWNER_UID", os.getuid())
    target = tmp_path / "approval.json"
    raw = b'{"state":"approved"}\n'
    close_events: list[int] = []
    real_close = creator.os.close
    real_fsync = creator.os.fsync
    injected = False

    def tracked_close(descriptor: int) -> None:
        close_events.append(descriptor)
        real_close(descriptor)

    def injecting_fsync(descriptor: int) -> None:
        nonlocal injected
        real_fsync(descriptor)
        if not injected:
            injected = True
            os.kill(os.getpid(), signal.SIGTERM)

    monkeypatch.setattr(creator.os, "close", tracked_close)
    monkeypatch.setattr(creator.os, "fsync", injecting_fsync)
    previous = signal.getsignal(signal.SIGTERM)
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, set())
    signal.signal(signal.SIGTERM, creator.signal_handler)
    try:
        with pytest.raises(creator.ApprovalInterrupted):
            creator.publish_exclusive(target, raw)
    finally:
        signal.signal(signal.SIGTERM, previous)
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
    assert injected is True
    assert len(close_events) >= 2
    assert target.read_bytes() == raw
    info = target.stat(follow_symlinks=False)
    assert stat.S_IMODE(info.st_mode) == 0o400
    assert info.st_uid == os.getuid() and info.st_nlink == 1


def test_creator_audits_freshness_before_tls_or_publication() -> None:
    source = CREATOR.read_text()
    main = source[source.index("def main()") :]
    assert main.index("validate_controller_contract(controller, hashes)") < main.index(
        "audited = controller.audit(hashes)"
    )
    assert main.index("audited = controller.audit(hashes)") < main.index(
        "_paths, private_tls = controller.tls_binding()"
    )
    assert main.index("_paths, private_tls = controller.tls_binding()") < main.index(
        "publish_exclusive(controller.APPROVAL, expected)"
    )
    gate_source = GATE_CONTROLLER.read_text()
    audit = gate_source[gate_source.index("def audit(") : gate_source.index("def main()")]
    assert "prove_fresh()" in audit
    assert "submit_once(" not in audit
    assert "publish_exclusive(" not in audit


def test_envelope_is_descriptor_bound_and_retains_launcher_fd() -> None:
    text = ENVELOPE.read_text()
    assert '"$0" == /proc/self/fd/8' in text
    assert '"${BASH_SOURCE[0]}" == /proc/self/fd/8' in text
    assert 'exec 9<"$bundle/launch.sh"' in text
    assert 'cd "$bundle"' in text
    assert text.index('exec 9<"$bundle/launch.sh"') < text.index('cd "$bundle"')
    assert 'os.execve("/usr/bin/bash",["/usr/bin/bash","-p","/proc/self/fd/9",mode],environment)' in text
    assert re.search(r'EXPECTED_APPROVAL_SHA256":"[0-9a-f]{64}', text) is None


def test_audit_execve_has_exact_clean_environment_and_argv(tmp_path: Path) -> None:
    inherited = {
        "TMUX": "tmux-socket,1,0",
        "TMUX_PANE": "%0",
        "HOSTILE": "not-forwarded",
        "THRIFT_TLS_CL_CERT_PATH": "/dummy/private/tls",
        "THRIFT_TLS_CL_KEY_PATH": "/dummy/private/tls",
        "EXPECTED_APPROVAL_SHA256": "a" * 64,
    }
    result, payload = capture_bootstrap(tmp_path, "audit", inherited)
    assert result.returncode == 0 and result.stdout == b"" and result.stderr == b""
    assert payload is not None
    assert payload["path"] == "/usr/bin/bash"
    assert payload["argv"] == ["/usr/bin/bash", "-p", "/proc/self/fd/9", "audit"]
    environment = payload["environment"]
    assert isinstance(environment, dict)
    assert "HOSTILE" not in environment
    assert "EXPECTED_APPROVAL_SHA256" not in environment
    assert "THRIFT_TLS_CL_CERT_PATH" not in environment
    assert "THRIFT_TLS_CL_KEY_PATH" not in environment
    assert environment["LAUNCHER_FD"] == "9"
    assert environment["TMUX"] == inherited["TMUX"]
    creator = load_creator()
    assert {key: environment[name] for key, name in creator.HASH_ENV.items()} == creator.BUNDLE_HASHES
    assert set(environment) == {
        "HOME",
        "USER",
        "LOGNAME",
        "PATH",
        "SHELL",
        "LANG",
        "LC_ALL",
        "TZ",
        "SLURM_CLUSTER_NAME",
        "PYTHONDONTWRITEBYTECODE",
        "PYTHONNOUSERSITE",
        "PYTHONSAFEPATH",
        "GIT_ATTR_NOSYSTEM",
        "GIT_CONFIG_GLOBAL",
        "GIT_CONFIG_SYSTEM",
        "GIT_NO_REPLACE_OBJECTS",
        "GIT_OPTIONAL_LOCKS",
        "GIT_TERMINAL_PROMPT",
        "TMUX",
        "TMUX_PANE",
        "LAUNCHER_FD",
        *creator.HASH_ENV.values(),
    }


def test_execute_execve_keeps_private_values_out_of_argv(tmp_path: Path) -> None:
    inherited = {
        "TMUX": "tmux-socket,1,0",
        "TMUX_PANE": "%0",
        "THRIFT_TLS_CL_CERT_PATH": "/dummy/private/tls",
        "THRIFT_TLS_CL_KEY_PATH": "/dummy/private/tls",
        "EXPECTED_APPROVAL_SHA256": "b" * 64,
    }
    result, payload = capture_bootstrap(tmp_path, "execute", inherited)
    assert result.returncode == 0 and result.stdout == b"" and result.stderr == b""
    assert payload is not None
    assert payload["argv"] == ["/usr/bin/bash", "-p", "/proc/self/fd/9", "execute"]
    environment = payload["environment"]
    assert isinstance(environment, dict)
    assert environment["EXPECTED_APPROVAL_SHA256"] == "b" * 64
    assert environment["THRIFT_TLS_CL_CERT_PATH"] == "/dummy/private/tls"
    assert environment["THRIFT_TLS_CL_KEY_PATH"] == "/dummy/private/tls"
    argv = json.dumps(payload["argv"])
    assert "/dummy/private/tls" not in argv and "b" * 64 not in argv
    creator = load_creator()
    assert set(environment) == {
        "HOME",
        "USER",
        "LOGNAME",
        "PATH",
        "SHELL",
        "LANG",
        "LC_ALL",
        "TZ",
        "SLURM_CLUSTER_NAME",
        "PYTHONDONTWRITEBYTECODE",
        "PYTHONNOUSERSITE",
        "PYTHONSAFEPATH",
        "GIT_ATTR_NOSYSTEM",
        "GIT_CONFIG_GLOBAL",
        "GIT_CONFIG_SYSTEM",
        "GIT_NO_REPLACE_OBJECTS",
        "GIT_OPTIONAL_LOCKS",
        "GIT_TERMINAL_PROMPT",
        "TMUX",
        "TMUX_PANE",
        "LAUNCHER_FD",
        "EXPECTED_APPROVAL_SHA256",
        "THRIFT_TLS_CL_CERT_PATH",
        "THRIFT_TLS_CL_KEY_PATH",
        *creator.HASH_ENV.values(),
    }


@pytest.mark.parametrize(
    "environment",
    [
        {"TMUX": "tmux-socket,1,0", "TMUX_PANE": "%0"},
        {
            "TMUX": "tmux-socket,1,0",
            "TMUX_PANE": "%0",
            "THRIFT_TLS_CL_CERT_PATH": "/dummy/private/tls",
            "THRIFT_TLS_CL_KEY_PATH": "/dummy/private/tls",
            "EXPECTED_APPROVAL_SHA256": "not-a-hash",
        },
    ],
)
def test_execute_rejects_missing_or_invalid_private_bindings(tmp_path: Path, environment: dict[str, str]) -> None:
    result, payload = capture_bootstrap(tmp_path, "execute", environment)
    assert result.returncode == 2
    assert result.stdout == b"" and result.stderr == b""
    assert payload is None


def test_runtime_files_have_only_fresh_v28_namespaces() -> None:
    runtime = CREATOR.read_text() + ENVELOPE.read_text()
    assert "k3_registry_pull_gate_20260920t153000z_v28" in runtime
    assert "k3-reg-pull-153000-v28" in runtime
    assert "k3-reg-pull-v28:" in runtime
    assert "20260920t142000z_v27" not in runtime
    assert "k3-reg-pull-142000-v27" not in runtime
    assert "k3-reg-pull-v27:" not in runtime
