from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import os
import signal
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).parent
RECOVERY_HELPER = (
    HERE.parent
    / "vmvm_owner_lifecycle_v4_scratch_recovery_7d204ee4a313968c25bfbda7"
    / "recover_vmvm_owner_lifecycle_v4_scratch.py"
)


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def completed(stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def bound(module, payload: bytes = b"x", digest_value: str | None = None):
    return module.BoundFile(
        -1, payload, digest_value or hashlib.sha256(payload).hexdigest(), (1, 2, 0, 0, 1, len(payload))
    )


def bundle_files(control):
    return {
        "README.md": {"mode": "0400", "sha256": "a" * 64, "size": 1},
        "control.py": {"mode": "0500", "sha256": "1" * 64, "size": 1},
        "recover_vmvm_owner_lifecycle_v4_scratch.py": {
            "mode": "0500",
            "sha256": control.RECOVERY_HELPER_SHA256,
            "size": 1,
        },
        "run_stage.sbatch": {"mode": "0500", "sha256": "2" * 64, "size": 1},
    }


def test_fixed_lineage_and_fresh_namespace() -> None:
    control = load("controls_lineage", "control.py")
    assert control.BASE_COMMIT == "bf22bf5c6228da3efd14e8279ca61d9ab64c6116"
    assert control.BASE_TREE == "0c29f9985332e20865b1696f4b90d96512cfdcf1"
    assert control.RECOVERY_SUBTREE == "64cbc0a1c180b29b2b0a85820a8e3031f0437fda"
    assert control.RECOVERY_HELPER_SHA256 == "faf05cc04b15c0193d575c6cb1a946bd7677966497e4db53db6abf53c97a6840"
    assert control.TOKEN == "f6ce50ed0fbe4782ecf8b9af"
    assert all(control.TOKEN in str(path) for path in control._namespace_paths())
    assert control.TARGET_NODE == "cpu-140-255"
    assert control.QUARANTINE_ROOT == control.TARGET_ROOT.with_name(
        "tianhaowu-vmvm-owner-lifecycle-9d7841b36-v4-scratch-quarantine-7d204ee4a313968c25bfbda7"
    )


def test_freezer_accepts_only_full_git_object_ids() -> None:
    freezer = load("controls_freezer_ids", "freeze_controls.py")
    assert freezer.GIT_OBJECT_RE.fullmatch("a" * 40)
    assert freezer.GIT_OBJECT_RE.fullmatch("a" * 39) is None
    assert freezer.GIT_OBJECT_RE.fullmatch("a" * 64) is None


def test_sbatch_is_held_pinned_singleton_with_complete_export_only(tmp_path: Path) -> None:
    control = load("controls_sbatch", "control.py")
    command = control.sbatch_command("audit", tmp_path / "env")
    assert command.count("--hold") == 1
    assert "--nodelist=cpu-140-255" in command
    assert "--nodes=1" in command
    assert "--ntasks=1" in command
    assert "--cpus-per-task=1" in command
    assert "--exclusive" in command
    assert "--no-requeue" in command
    assert "--time=00:15:00" in command
    assert sum(item.startswith("--export-file=") for item in command) == 1
    assert not any(item.startswith("--export=") for item in command)
    assert command[-1] == str(control.BATCH)
    assert str(control.TARGET_ROOT) not in "\0".join(command)


def test_stage_names_and_receipts_are_distinct() -> None:
    control = load("controls_names", "control.py")
    assert control.AUDIT_JOB_NAME != control.RECOVERY_JOB_NAME
    assert control.AUDIT_AUTHORIZATION != control.RECOVERY_AUTHORIZATION
    assert control.AUDIT_RECEIPT != control.RECOVERY_RECEIPT
    assert control.AUDIT_RESERVATION != control.RECOVERY_RESERVATION
    assert control.AUDIT_LOG != control.RECOVERY_LOG


def test_job_environment_is_minimal_and_secret_free() -> None:
    control = load("controls_env", "control.py")
    manifest = {
        "files": {
            "control.py": {"sha256": "1" * 64},
            "run_stage.sbatch": {"sha256": "2" * 64},
        }
    }
    values = control._job_environment(
        "audit", bound(control, digest_value="3" * 64), bound(control, digest_value="4" * 64), manifest
    )
    assert not any(name.startswith(control.FORBIDDEN_ENV_PREFIXES) for name in values)
    assert not (set(values) & control.FORBIDDEN_ENV_NAMES)
    assert values["VMVM_V4_RECOVERY_STAGE"] == "audit"
    assert values["HOME"] == "/nonexistent"
    assert "VMVM_V4_RECOVERY_AUTH_SHA256" in values


def test_export_file_is_nul_delimited_and_scrubbed_in_place(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    control = load("controls_export", "control.py")
    monkeypatch.setattr(control.tempfile, "mkdtemp", lambda **_kwargs: str(tmp_path / "private"))
    (tmp_path / "private").mkdir(mode=0o700)
    path, parent_fd, file_fd = control._write_export({"B": "two", "A": "one"})
    assert path.read_bytes() == b"A=one\0B=two\0"
    assert stat.S_IMODE(path.stat().st_mode) == 0o400
    control._scrub_export(path, parent_fd, file_fd)
    assert path.parent.is_dir()
    assert path.read_bytes() == b""


def test_export_scrub_never_unlinks_a_swapped_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    control = load("controls_export_file_swap", "control.py")
    private = tmp_path / "private"
    monkeypatch.setattr(control.tempfile, "mkdtemp", lambda **_kwargs: str(private))
    private.mkdir(mode=0o700)
    path, parent_fd, file_fd = control._write_export({"A": "secret"})
    displaced = private / "owned.displaced"
    real_write_all = control._write_all
    swapped = False

    def swap_then_write(descriptor: int, payload: bytes) -> None:
        nonlocal swapped
        if not swapped:
            swapped = True
            path.rename(displaced)
            path.write_bytes(b"replacement")
            path.chmod(0o400)
        real_write_all(descriptor, payload)

    monkeypatch.setattr(control, "_write_all", swap_then_write)
    with pytest.raises(control.ControlError, match="binding"):
        control._scrub_export(path, parent_fd, file_fd)
    assert displaced.read_bytes() == b""
    assert path.read_bytes() == b"replacement"


def test_export_scrub_never_removes_a_swapped_parent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    control = load("controls_export_parent_swap", "control.py")
    private = tmp_path / "private"
    displaced = tmp_path / "owned.displaced"
    monkeypatch.setattr(control.tempfile, "mkdtemp", lambda **_kwargs: str(private))
    private.mkdir(mode=0o700)
    path, parent_fd, file_fd = control._write_export({"A": "secret"})
    private.rename(displaced)
    private.mkdir(mode=0o700)
    (private / "replacement").write_bytes(b"untouched")

    control._scrub_export(path, parent_fd, file_fd)

    assert (displaced / path.name).read_bytes() == b""
    assert (private / "replacement").read_bytes() == b"untouched"
    source = inspect.getsource(control._scrub_export)
    assert "unlink" not in source
    assert "rmdir" not in source


def test_static_preflight_has_no_submit_or_control_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    control = load("controls_preflight", "control.py")
    manifest = bound(control, digest_value="a" * 64)
    calls: list[object] = []
    monkeypatch.setattr(control, "_manifest", lambda: (manifest, {"files": bundle_files(control)}))
    monkeypatch.setattr(control, "_validate_tool", lambda path: calls.append(("tool", path)))
    monkeypatch.setattr(control, "_require_private_directory", lambda path, **kwargs: calls.append(("directory", path)))
    monkeypatch.setattr(control, "_require_fresh", lambda paths: calls.append(("fresh", tuple(paths))))
    monkeypatch.setattr(control, "_require_log_namespace_fresh", lambda: calls.append("logs"))
    monkeypatch.setattr(control, "_require_scheduler_names_fresh", lambda: calls.append("names"))
    monkeypatch.setattr(control, "open_bound_file", lambda *_args, **_kwargs: bound(control))
    monkeypatch.setattr(control, "stable_terminal_job", lambda *_args, **_kwargs: "b" * 64)
    monkeypatch.setattr(
        control, "_commit_publication", lambda action, path, value: calls.append(("publish", path, value))
    )
    monkeypatch.setattr(control, "_run", lambda *_args, **_kwargs: pytest.fail("preflight must not submit or mutate"))
    control.static_preflight()
    published = next(item for item in calls if isinstance(item, tuple) and item[0] == "publish")
    assert published[1] == control.PREFLIGHT_RECEIPT
    assert published[2]["state"] == "ready"


def test_static_preflight_call_graph_has_only_read_only_scheduler_queries() -> None:
    control = load("controls_preflight_static", "control.py")
    source = "\n".join(
        inspect.getsource(function)
        for function in (
            control.static_preflight,
            control._require_scheduler_names_fresh,
            control._require_stage_name_fresh,
            control.stable_terminal_job,
            control._squeue_absent,
            control._accounting_snapshot,
        )
    )
    assert "SBATCH" not in source
    assert "SCONTROL" not in source
    assert "SCANCEL" not in source
    assert "SQUEUE" in source and "SACCT" in source


def test_old_job_requires_two_identical_accounting_reads_and_queue_absence(monkeypatch: pytest.MonkeyPatch) -> None:
    control = load("controls_old_job", "control.py")
    fields = tuple(control.FAILED_JOB_EXPECTED)
    line = "|".join(control.FAILED_JOB_EXPECTED[name] for name in fields).encode() + b"\n"
    calls: list[tuple[str, ...]] = []

    def fake_run(arguments, **_kwargs):
        args = tuple(arguments)
        calls.append(args)
        if args[0] == str(control.SQUEUE):
            return completed()
        return completed(line)

    monkeypatch.setattr(control, "_run", fake_run)
    monkeypatch.setattr(control.time, "sleep", lambda _seconds: None)
    assert (
        control.stable_terminal_job(control.FAILED_JOB_ID, expected=control.FAILED_JOB_EXPECTED)
        == hashlib.sha256(line).hexdigest()
    )
    assert [call[0] for call in calls] == [
        str(control.SQUEUE),
        str(control.SACCT),
        str(control.SQUEUE),
        str(control.SACCT),
    ]


def test_old_job_rejects_changed_second_accounting_read(monkeypatch: pytest.MonkeyPatch) -> None:
    control = load("controls_old_job_drift", "control.py")
    fields = tuple(control.FAILED_JOB_EXPECTED)
    good = "|".join(control.FAILED_JOB_EXPECTED[name] for name in fields).encode() + b"\n"
    changed = good + b"\n"
    accounting = iter((good, changed))

    def fake_run(arguments, **_kwargs):
        return completed() if arguments[0] == str(control.SQUEUE) else completed(next(accounting))

    monkeypatch.setattr(control, "_run", fake_run)
    monkeypatch.setattr(control.time, "sleep", lambda _seconds: None)
    with pytest.raises(control.ControlError, match="old_job"):
        control.stable_terminal_job(control.FAILED_JOB_ID, expected=control.FAILED_JOB_EXPECTED)


def test_scheduler_namespace_checks_queue_and_history(monkeypatch: pytest.MonkeyPatch) -> None:
    control = load("controls_scheduler_names", "control.py")
    calls = []
    monkeypatch.setattr(control, "_run", lambda args, **_kwargs: calls.append(tuple(args)) or completed())
    control._require_scheduler_names_fresh()
    assert len(calls) == 4
    assert sum(call[0] == str(control.SQUEUE) for call in calls) == 2
    assert sum(call[0] == str(control.SACCT) for call in calls) == 2


def test_scheduler_namespace_rejects_history(monkeypatch: pytest.MonkeyPatch) -> None:
    control = load("controls_scheduler_collision", "control.py")

    def fake_run(args, **_kwargs):
        return completed(b"123|collision|FAILED\n") if args[0] == str(control.SACCT) else completed()

    monkeypatch.setattr(control, "_run", fake_run)
    with pytest.raises(control.ControlError, match="freshness"):
        control._require_scheduler_names_fresh()


def test_held_identity_needs_two_byte_identical_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    control = load("controls_held", "control.py")
    monkeypatch.setattr(control, "_held_projection", lambda _record, _job_id, _stage: ("ok",))
    outputs = iter((b"JobId=12 A=1\n", b"JobId=12 A=2\n", b"JobId=12 A=2\n"))
    monkeypatch.setattr(control, "_run", lambda *_args, **_kwargs: completed(next(outputs)))
    monkeypatch.setattr(control.time, "sleep", lambda _seconds: None)
    assert control._stable_held("12", "audit") == hashlib.sha256(b"JobId=12 A=2\n").hexdigest()


def test_launch_releases_exactly_once_after_two_held_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    control = load("controls_launch", "control.py")
    manifest_value = {"files": bundle_files(control)}
    manifest = bound(control, digest_value="3" * 64)
    preflight = bound(control, digest_value="5" * 64)
    authorization = bound(control, digest_value="4" * 64)
    auth_value = control._authorization_common("audit", manifest.digest, "5" * 64, bundle_files(control)) | {
        "artifact_type": "vmvm_v4_scratch_recovery_audit_authorization_v1",
        "receipt_path": str(control.AUDIT_RECEIPT),
        "root_cardinality": [0, 1],
        "schema_version": 1,
    }
    actions: list[object] = []
    monkeypatch.setattr(control, "_manifest", lambda: (manifest, manifest_value))
    monkeypatch.setattr(
        control,
        "_load_preflight",
        lambda: (preflight, {"bundle_manifest_sha256": manifest.digest, "failed_job_accounting_sha256": "x" * 64}),
    )
    monkeypatch.setattr(control, "_load_authorization", lambda stage: (authorization, auth_value))
    monkeypatch.setattr(control, "_require_fresh", lambda _paths: None)
    monkeypatch.setattr(control, "_require_private_directory", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(control, "_require_stage_name_fresh", lambda _stage: None)
    monkeypatch.setattr(control, "stable_terminal_job", lambda *_args, **_kwargs: "x" * 64)
    monkeypatch.setattr(control, "_write_export", lambda _values: (Path("/tmp/fake-env"), 99, 98))
    monkeypatch.setattr(
        control, "_scrub_export", lambda path, parent_fd, file_fd: actions.append(("scrub", path, parent_fd, file_fd))
    )
    monkeypatch.setattr(control, "_create_reservation", lambda _path: (87, 88, "reservation"))
    monkeypatch.setattr(
        control, "_seal_reservation", lambda parent, fd, name, payload: actions.append(("reservation", fd, payload))
    )
    monkeypatch.setattr(control.os, "close", lambda _fd: None)
    monkeypatch.setattr(
        control,
        "_stable_held",
        lambda job, stage: (actions.append(("held", job, stage)), "f" * 64)[1],
    )
    monkeypatch.setattr(
        control,
        "_bounded_submit",
        lambda command: actions.append(tuple(command)) or control.SubmitAttempt(b"123\n", b"", 0, "completed"),
    )
    monkeypatch.setattr(control, "_recover_submission", lambda _stage, direct: direct)
    monkeypatch.setattr(control.signal, "pthread_sigmask", lambda *_args: None)

    def fake_run(args, **_kwargs):
        actions.append(tuple(args))
        return completed()

    monkeypatch.setattr(control, "_run", fake_run)
    control.launch("audit")
    assert actions.count(("held", "123", "audit")) == 1
    assert actions.count((str(control.SCONTROL), "-M", control.CLUSTER, "release", "123")) == 1
    submit = next(item for item in actions if isinstance(item, tuple) and item and item[0] == str(control.SBATCH))
    assert "--hold" in submit
    assert not any(str(item).startswith("--export=") for item in submit)
    assert (
        actions.index(("held", "123", "audit"))
        < next(index for index, item in enumerate(actions) if isinstance(item, tuple) and item[0] == "scrub")
        < actions.index((str(control.SCONTROL), "-M", control.CLUSTER, "release", "123"))
    )


def test_launch_cancels_exact_id_on_held_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    control = load("controls_launch_cancel", "control.py")
    manifest_value = {"files": bundle_files(control)}
    manifest = bound(control, digest_value="3" * 64)
    preflight = bound(control, digest_value="5" * 64)
    authorization = bound(control, digest_value="4" * 64)
    auth_value = control._authorization_common("audit", manifest.digest, "5" * 64, bundle_files(control)) | {
        "artifact_type": "vmvm_v4_scratch_recovery_audit_authorization_v1",
        "receipt_path": str(control.AUDIT_RECEIPT),
        "root_cardinality": [0, 1],
        "schema_version": 1,
    }
    monkeypatch.setattr(control, "_manifest", lambda: (manifest, manifest_value))
    monkeypatch.setattr(
        control,
        "_load_preflight",
        lambda: (preflight, {"bundle_manifest_sha256": manifest.digest, "failed_job_accounting_sha256": "x" * 64}),
    )
    monkeypatch.setattr(control, "_load_authorization", lambda stage: (authorization, auth_value))
    monkeypatch.setattr(control, "_require_fresh", lambda _paths: None)
    monkeypatch.setattr(control, "_require_private_directory", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(control, "_require_stage_name_fresh", lambda _stage: None)
    monkeypatch.setattr(control, "stable_terminal_job", lambda *_args, **_kwargs: "x" * 64)
    monkeypatch.setattr(control, "_write_export", lambda _values: (Path("/tmp/fake-env"), 99, 98))
    monkeypatch.setattr(control, "_scrub_export", lambda *_args: None)
    monkeypatch.setattr(control, "_create_reservation", lambda _path: (87, 88, "reservation"))
    monkeypatch.setattr(control, "_seal_reservation", lambda *_args: None)
    monkeypatch.setattr(control.os, "close", lambda _fd: None)
    monkeypatch.setattr(
        control, "_stable_held", lambda *_args: (_ for _ in ()).throw(control.ControlError("scheduler"))
    )
    monkeypatch.setattr(
        control,
        "_bounded_submit",
        lambda _command: control.SubmitAttempt(b"321\n", b"", 0, "completed"),
    )
    monkeypatch.setattr(control, "_recover_submission", lambda _stage, direct: direct)
    cancelled = []
    monkeypatch.setattr(control, "_cancel", lambda job: cancelled.append(job))
    monkeypatch.setattr(control, "_run", lambda *_args, **_kwargs: completed(b"321\n"))
    with pytest.raises(control.ControlError, match="scheduler"):
        control.launch("audit")
    assert cancelled == ["321"]


def test_audit_authorization_is_separate_and_has_no_root_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    control = load("controls_audit_auth", "control.py")
    manifest = bound(control, digest_value="1" * 64)
    preflight = bound(control, digest_value="2" * 64)
    preflight_value = {
        "bundle_manifest_sha256": manifest.digest,
        "failed_job_accounting_sha256": "3" * 64,
    }
    captured = {}
    monkeypatch.setattr(control, "_manifest", lambda: (manifest, {"files": bundle_files(control)}))
    monkeypatch.setattr(control, "_load_preflight", lambda: (preflight, preflight_value))
    monkeypatch.setattr(control, "_require_fresh", lambda _paths: None)
    monkeypatch.setattr(control, "_require_stage_name_fresh", lambda _stage: None)
    monkeypatch.setattr(control, "stable_terminal_job", lambda *_args, **_kwargs: "3" * 64)
    monkeypatch.setattr(
        control, "_commit_publication", lambda action, path, value: captured.update(path=path, value=value)
    )
    control.authorize_audit()
    assert captured["path"] == control.AUDIT_AUTHORIZATION
    assert captured["value"]["authorized_stage"] == "audit"
    assert captured["value"]["root_cardinality"] == [0, 1]
    assert "scratch_identity" not in captured["value"]


def test_recovery_authorization_embeds_exact_audit_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    control = load("controls_recovery_auth", "control.py")
    manifest = bound(control, digest_value="1" * 64)
    preflight = bound(control, digest_value="2" * 64)
    audit_auth = bound(control, digest_value="3" * 64)
    audit_value = {
        "artifact_type": "vmvm_v4_scratch_recovery_audit_receipt_v1",
        "audit_authorization_sha256": audit_auth.digest,
        "candidate_token": control.TOKEN,
        "inventory_sha256": "4" * 64,
        "job": {
            "cluster": control.CLUSTER,
            "job_id": "12",
            "job_name": control.AUDIT_JOB_NAME,
            "node": control.TARGET_NODE,
        },
        "quiescence": {"observations": 2, "state": "absent"},
        "root": {"state": "absent"},
        "schema_version": 1,
        "state": "audited",
    }
    audit_receipt = bound(control, control.canonical(audit_value))
    preflight_value = {"bundle_manifest_sha256": manifest.digest, "failed_job_accounting_sha256": "5" * 64}
    captured = {}
    monkeypatch.setattr(control, "_manifest", lambda: (manifest, {"files": bundle_files(control)}))
    monkeypatch.setattr(control, "_load_preflight", lambda: (preflight, preflight_value))
    monkeypatch.setattr(control, "_load_authorization", lambda stage: (audit_auth, {}))
    monkeypatch.setattr(control, "_load_audit_receipt", lambda: (audit_receipt, audit_value))
    monkeypatch.setattr(control, "_require_fresh", lambda _paths: None)
    monkeypatch.setattr(control, "_require_stage_name_fresh", lambda _stage: None)
    monkeypatch.setattr(
        control, "stable_terminal_job", lambda job, **_kwargs: "5" * 64 if job == control.FAILED_JOB_ID else "6" * 64
    )
    monkeypatch.setattr(control, "_validate_stage_log", lambda _stage, _job: "7" * 64)
    monkeypatch.setattr(
        control, "_commit_publication", lambda action, path, value: captured.update(path=path, value=value)
    )
    control.authorize_recovery()
    assert captured["path"] == control.RECOVERY_AUTHORIZATION
    assert captured["value"]["audit_receipt"] == audit_value
    assert captured["value"]["audit_receipt_sha256"] == audit_receipt.digest
    assert captured["value"]["audit_public_log_sha256"] == "7" * 64


def test_canonical_parser_rejects_extra_newline() -> None:
    control = load("controls_json", "control.py")
    item = bound(control, b'{"artifact_type":"x"}\n\n')
    with pytest.raises(control.ControlError, match="binding"):
        control.parse_canonical_json(item, artifact_type="x")


def test_external_hashes_are_required_at_every_authority_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    control = load("controls_external_hash", "control.py")
    monkeypatch.setattr(control.os, "environ", {})
    with pytest.raises(control.ControlError, match="authorization"):
        control._load_preflight()
    with pytest.raises(control.ControlError, match="authorization"):
        control._load_authorization("audit")
    with pytest.raises(control.ControlError, match="authorization"):
        control._load_authorization("recover")
    with pytest.raises(control.ControlError, match="authorization"):
        control._load_audit_receipt()


def test_open_bound_file_rejects_symlink_and_hardlink(tmp_path: Path) -> None:
    control = load("controls_bound", "control.py")
    target = tmp_path / "target"
    target.write_bytes(b"value")
    target.chmod(0o400)
    symlink = tmp_path / "symlink"
    symlink.symlink_to(target)
    with pytest.raises(control.ControlError, match="binding"):
        control.open_bound_file(symlink, mode=0o400)
    hardlink = tmp_path / "hardlink"
    os.link(target, hardlink)
    with pytest.raises(control.ControlError, match="binding"):
        control.open_bound_file(target, mode=0o400)


def test_publish_exclusive_refuses_existing_target(tmp_path: Path) -> None:
    control = load("controls_publish", "control.py")
    path = tmp_path / "receipt"
    path.write_bytes(b"old")
    path.chmod(0o400)
    with pytest.raises(control.ControlError, match="freshness"):
        control.publish_exclusive(path, {"state": "new"})
    assert path.read_bytes() == b"old"


def test_public_records_are_bounded_and_do_not_echo_inputs() -> None:
    control = load("controls_public", "control.py")
    secret = "do-not-print-this"
    for action in control.PUBLIC_KINDS:
        for state in ("success", "failed"):
            raw = control.public_record(action, state, "success")
            assert len(raw) <= 384
            assert secret.encode() not in raw
            value = json.loads(raw)
            assert set(value) == {"action", "artifact_type", "category", "stage", "state"}


def test_node_environment_rejects_credential_names(monkeypatch: pytest.MonkeyPatch) -> None:
    control = load("controls_node_env", "control.py")
    values = {
        "VMVM_V4_RECOVERY_STAGE": "audit",
        "VMVM_V4_RECOVERY_AUTH_FD": "5",
        "VMVM_V4_RECOVERY_AUTH_SHA256": "1" * 64,
        "VMVM_V4_RECOVERY_CONTROL_SHA256": "2" * 64,
        "VMVM_V4_RECOVERY_HELPER_FD": "4",
        "VMVM_V4_RECOVERY_HELPER_SHA256": "3" * 64,
        "VMVM_V4_RECOVERY_RECEIPT_PATH": str(control.AUDIT_RECEIPT),
        "SLURM_CLUSTER_NAME": control.CLUSTER,
        "SLURMD_NODENAME": control.TARGET_NODE,
        "SLURM_JOB_ID": "12",
        "SLURM_JOB_NAME": control.AUDIT_JOB_NAME,
        "X2P_PROXY_URL": "secret",
    }
    monkeypatch.setattr(control.os, "environ", values)
    with pytest.raises(control.ControlError, match="authorization"):
        control._validate_node_environment("audit")


def test_absent_root_audit_performs_two_owner_scans_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    control = load("controls_absent_root", "control.py")
    target = tmp_path / "missing"
    quarantine = tmp_path / "quarantine"
    monkeypatch.setattr(control, "TARGET_ROOT", target)
    monkeypatch.setattr(control, "QUARANTINE_ROOT", quarantine)
    scans = []
    monkeypatch.setattr(control, "_same_uid_target_reference", lambda: scans.append(True) and False)
    monkeypatch.setattr(control, "_same_uid_quarantine_reference", lambda: False)
    monkeypatch.setattr(control.time, "sleep", lambda _seconds: None)
    helper = SimpleNamespace(
        _IN_Q_OVERFLOW=0x4000,
        _open_absolute_directory=lambda path: os.open(path, os.O_RDONLY | os.O_DIRECTORY),
        _open_watch=lambda _fd: os.open("/dev/null", os.O_RDONLY),
        _read_events=lambda _fd: [],
    )
    root, commitment, inventory, parent_fd, root_fd, parent_watch_fd, root_watch_fd = control._root_observation(
        helper, prove_quiescence=True
    )
    try:
        assert root == {"state": "absent"}
        assert commitment == control.digest(control.canonical([]))
        assert inventory is None and root_fd == -1
        assert len(scans) == 2
    finally:
        control._close_observation(inventory, parent_fd, root_fd, parent_watch_fd, root_watch_fd)


def test_present_root_audit_uses_owner_scan_not_control_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    control = load("controls_present_root", "control.py")
    target = tmp_path / "scratch"
    target.mkdir(mode=0o700)
    monkeypatch.setattr(control, "TARGET_ROOT", target)
    monkeypatch.setattr(control.time, "sleep", lambda _seconds: None)

    class Inventory:
        entries = {}
        identities = set()

        def close(self):
            pass

    identity = {
        "device": target.stat().st_dev,
        "inode": target.stat().st_ino,
        "mode": 0o700,
        "mount_id": 1,
        "owner_uid": os.getuid(),
    }
    calls = []
    helper = SimpleNamespace(
        _IN_Q_OVERFLOW=0x4000,
        _open_absolute_directory=lambda path: os.open(path, os.O_RDONLY | os.O_DIRECTORY),
        _open_watch=lambda _fd: os.open("/dev/null", os.O_RDONLY),
        _read_events=lambda _fd: [],
        _known_mount_ids=lambda: {1},
        descriptor_identity=lambda _fd, _known=None: identity,
        _directory_identity_at=lambda *_args: identity,
        _inventory=lambda _fd: ("empty", (), Inventory()),
        _same_uid_process_references=lambda *_args: calls.append("scan") and False,
        _quiesce=lambda *_args: pytest.fail("read-only audit must not request ControlMaster exit"),
    )
    root, _commitment, inventory, parent_fd, root_fd, parent_watch_fd, root_watch_fd = control._root_observation(
        helper, prove_quiescence=True
    )
    try:
        assert root["state"] == "present"
        assert calls == ["scan", "scan"]
    finally:
        control._close_observation(inventory, parent_fd, root_fd, parent_watch_fd, root_watch_fd)


def test_absent_root_audit_rejects_target_name_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    control = load("controls_absent_race", "control.py")
    target = tmp_path / "missing"
    quarantine = tmp_path / "quarantine"
    monkeypatch.setattr(control, "TARGET_ROOT", target)
    monkeypatch.setattr(control, "QUARANTINE_ROOT", quarantine)
    monkeypatch.setattr(control, "_same_uid_target_reference", lambda: False)
    monkeypatch.setattr(control, "_same_uid_quarantine_reference", lambda: False)
    monkeypatch.setattr(control.time, "sleep", lambda _seconds: None)
    events = [[(0x100, 0, target.name.encode())]]
    helper = SimpleNamespace(
        _IN_Q_OVERFLOW=0x4000,
        _open_absolute_directory=lambda path: os.open(path, os.O_RDONLY | os.O_DIRECTORY),
        _open_watch=lambda _fd: os.open("/dev/null", os.O_RDONLY),
        _read_events=lambda _fd: events.pop(0),
    )
    with pytest.raises(control.ControlError, match="root_state"):
        control._root_observation(helper, prove_quiescence=True)


def test_final_absent_revalidation_rejects_late_target_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    control = load("controls_absent_final_race", "control.py")
    target = tmp_path / "missing"
    quarantine = tmp_path / "quarantine"
    monkeypatch.setattr(control, "TARGET_ROOT", target)
    monkeypatch.setattr(control, "QUARANTINE_ROOT", quarantine)
    monkeypatch.setattr(control, "_same_uid_target_reference", lambda: False)
    monkeypatch.setattr(control, "_same_uid_quarantine_reference", lambda: False)
    parent_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    helper = SimpleNamespace(
        _IN_Q_OVERFLOW=0x4000,
        _read_events=lambda _fd: [(0x100, 0, target.name.encode())],
    )
    try:
        with pytest.raises(control.ControlError, match="root_state"):
            control._revalidate_observation(
                helper,
                {"state": "absent"},
                control.digest(control.canonical([])),
                None,
                parent_fd,
                -1,
                12,
                -1,
            )
    finally:
        os.close(parent_fd)


def test_final_quarantine_rejects_late_repopulation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    control = load("controls_recovery_final_race", "control.py")
    root = tmp_path / "scratch"
    root.mkdir(mode=0o700)
    quarantine = tmp_path / "quarantine"
    monkeypatch.setattr(control, "TARGET_ROOT", root)
    monkeypatch.setattr(control, "QUARANTINE_ROOT", quarantine)
    parent_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    info = os.fstat(root_fd)
    identity = {
        "device": info.st_dev,
        "inode": info.st_ino,
        "mode": 0o700,
        "mount_id": 1,
        "owner_uid": os.getuid(),
    }
    root.rename(quarantine)
    (quarantine / "late").write_bytes(b"late")
    inventory = SimpleNamespace(
        entries={"late": SimpleNamespace(identity=(1,), kind="regular")},
        identities={(1, 2)},
        close=lambda: None,
    )
    helper = SimpleNamespace(
        _known_mount_ids=lambda: {1},
        descriptor_identity=lambda _fd, _known=None: identity,
        _directory_identity_at=lambda *_args: identity,
        _inventory=lambda _fd: ("regular_only", (), inventory),
        _same_uid_process_references=lambda *_args: False,
    )
    monkeypatch.setattr(control, "_same_uid_target_reference", lambda: False)
    monkeypatch.setattr(control, "_same_uid_quarantine_reference", lambda: False)
    try:
        with pytest.raises(control.ControlError, match="root_state"):
            control._revalidate_quarantined_root(
                helper,
                identity,
                "empty",
                control.digest(control.canonical([])),
                parent_fd,
                root_fd,
                12,
                13,
            )
    finally:
        os.close(root_fd)
        os.close(parent_fd)


def test_final_quarantine_continuously_binds_real_move_and_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    control = load("controls_recovery_final_success", "control.py")
    helper = load_path("controls_recovery_real_helper", RECOVERY_HELPER)
    root = tmp_path / "scratch"
    quarantine = tmp_path / "quarantine"
    root.mkdir(mode=0o700)
    (root / "evidence").write_bytes(b"fixed")
    monkeypatch.setattr(control, "TARGET_ROOT", root)
    monkeypatch.setattr(control, "QUARANTINE_ROOT", quarantine)
    monkeypatch.setattr(control, "OWNER_UID", os.getuid())
    monkeypatch.setattr(control, "_same_uid_target_reference", lambda: False)
    monkeypatch.setattr(control, "_same_uid_quarantine_reference", lambda: False)
    monkeypatch.setattr(helper, "TARGET_ROOT", root)
    monkeypatch.setattr(helper, "QUARANTINE_ROOT", quarantine)
    monkeypatch.setattr(helper, "EXPECTED_UID", os.getuid())
    monkeypatch.setattr(helper, "_same_uid_process_references", lambda *_args: False)
    parent_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    parent_watch_fd = helper._open_watch(parent_fd)
    root_watch_fd = helper._open_watch(root_fd)
    identity = helper.descriptor_identity(root_fd)
    inventory_class, _sockets, inventory = helper._inventory(root_fd)
    inventory_sha = control._inventory_commitment(inventory)
    try:
        helper._quarantine_root_verified(parent_fd, root_fd, identity)
        control._revalidate_quarantined_root(
            helper,
            identity,
            inventory_class,
            inventory_sha,
            parent_fd,
            root_fd,
            parent_watch_fd,
            root_watch_fd,
        )
        assert not root.exists()
        assert (quarantine / "evidence").read_bytes() == b"fixed"
    finally:
        inventory.close()
        os.close(root_watch_fd)
        os.close(parent_watch_fd)
        os.close(root_fd)
        os.close(parent_fd)


def test_root_observation_resumes_only_exact_authorized_quarantine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    control = load("controls_resume_observation", "control.py")
    helper = load_path("controls_resume_observation_helper", RECOVERY_HELPER)
    target = tmp_path / "scratch"
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir(mode=0o700)
    (quarantine / "evidence").write_bytes(b"fixed")
    monkeypatch.setattr(control, "TARGET_ROOT", target)
    monkeypatch.setattr(control, "QUARANTINE_ROOT", quarantine)
    monkeypatch.setattr(control, "OWNER_UID", os.getuid())
    monkeypatch.setattr(control, "_same_uid_target_reference", lambda: False)
    monkeypatch.setattr(control, "_same_uid_quarantine_reference", lambda: False)
    monkeypatch.setattr(control.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(helper, "EXPECTED_UID", os.getuid())
    monkeypatch.setattr(helper, "_same_uid_process_references", lambda *_args: False)
    quarantine_fd = os.open(quarantine, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        identity = helper.descriptor_identity(quarantine_fd)
        inventory_class, _sockets, expected_inventory = helper._inventory(quarantine_fd)
        try:
            inventory_sha = control._inventory_commitment(expected_inventory)
        finally:
            expected_inventory.close()
    finally:
        os.close(quarantine_fd)
    audit_root = {"identity": identity, "inventory_class": inventory_class, "state": "present"}

    observation = control._root_observation(
        helper,
        prove_quiescence=True,
        authorized_quarantine=(audit_root, inventory_sha),
    )
    root, observed_sha, inventory, parent_fd, root_fd, parent_watch_fd, root_watch_fd = observation
    try:
        assert root == {**audit_root, "state": "quarantined"}
        assert observed_sha == inventory_sha
        control._revalidate_quarantined_root(
            helper,
            identity,
            inventory_class,
            inventory_sha,
            parent_fd,
            root_fd,
            parent_watch_fd,
            root_watch_fd,
            expect_move=False,
        )
    finally:
        control._close_observation(inventory, parent_fd, root_fd, parent_watch_fd, root_watch_fd)

    with pytest.raises(control.ControlError, match="root_state"):
        control._root_observation(
            helper,
            prove_quiescence=True,
            authorized_quarantine=(audit_root, "0" * 64),
        )
    target.mkdir(mode=0o700)
    with pytest.raises(control.ControlError, match="root_state"):
        control._root_observation(
            helper,
            prove_quiescence=True,
            authorized_quarantine=(audit_root, inventory_sha),
        )


def test_terminal_boundary_rejects_pending_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    control = load("controls_pending_signal", "control.py")
    calls = []
    monkeypatch.setattr(control.signal, "pthread_sigmask", lambda how, signals: calls.append((how, signals)))
    monkeypatch.setattr(control.signal, "sigpending", lambda: {signal.SIGTERM})
    with pytest.raises(control.Interrupted):
        control._enter_terminal_boundary()
    assert calls == [(signal.SIG_BLOCK, control.HANDLED_SIGNALS)]


@pytest.mark.parametrize(
    "action",
    (
        "node-audit",
        "node-recover",
    ),
)
def test_pending_signal_before_commit_blocks_publication(
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    control = load(f"controls_precommit_signal_{action}", "control.py")
    monkeypatch.setattr(control.signal, "pthread_sigmask", lambda *_args: None)
    monkeypatch.setattr(control.signal, "sigpending", lambda: {signal.SIGTERM})
    monkeypatch.setattr(
        control,
        "publish_exclusive",
        lambda *_args, **_kwargs: pytest.fail("pending signal must prevent publication"),
    )
    with pytest.raises(control.Interrupted):
        control._commit_publication(action, Path("/unused"), {"state": "success"})
    assert control._COMMITTED_ACTION is None


def test_pending_signal_after_irreversible_move_does_not_veto_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control = load("controls_postcommit_signal", "control.py")
    published = []
    monkeypatch.setattr(control.signal, "pthread_sigmask", lambda *_args: None)
    monkeypatch.setattr(control.signal, "sigpending", lambda: {signal.SIGTERM})
    monkeypatch.setattr(control, "publish_exclusive", lambda path, value: published.append((path, value)) or "a" * 64)

    assert (
        control._commit_publication(
            "node-recover",
            Path("/unused"),
            {"state": "quarantined"},
            irreversible=True,
        )
        == "a" * 64
    )
    assert published == [(Path("/unused"), {"state": "quarantined"})]
    assert control._COMMITTED_ACTION == "node-recover"


def test_irreversible_publication_accepts_exact_file_after_baseexception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control = load("controls_postcommit_publication", "control.py")
    path = tmp_path / "receipt.json"
    value = {"state": "quarantined"}
    real_publish = control.publish_exclusive
    monkeypatch.setattr(control, "OWNER_UID", os.getuid())
    monkeypatch.setattr(control.signal, "pthread_sigmask", lambda *_args: None)
    monkeypatch.setattr(control.signal, "sigpending", lambda: set())

    def publish_then_interrupt(target: Path, payload: object) -> str:
        real_publish(target, payload)
        raise KeyboardInterrupt

    monkeypatch.setattr(control, "publish_exclusive", publish_then_interrupt)
    assert control._commit_publication("node-recover", path, value, irreversible=True) == control.digest(
        control.canonical(value)
    )
    assert control._COMMITTED_ACTION == "node-recover"


def test_recovery_rejects_root_drift_before_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    control = load("controls_recovery_drift", "control.py")
    monkeypatch.setattr(control, "_validate_node_environment", lambda _stage: None)
    fake_match = SimpleNamespace(group=lambda _index: "3")
    monkeypatch.setattr(control, "FD_RE", SimpleNamespace(fullmatch=lambda _value: fake_match))
    monkeypatch.setattr(
        control,
        "_fd_from_env",
        lambda *_args, **_kwargs: bound(
            control, digest_value=control.RECOVERY_HELPER_SHA256 if "HELPER" in _args[0] else "1" * 64
        ),
    )
    audit = {"root": {"state": "absent"}, "inventory_sha256": "2" * 64}
    authorization = bound(control, digest_value="3" * 64)
    auth_value = control._authorization_common("recover", "4" * 64, "5" * 64, bundle_files(control)) | {
        "audit_receipt": audit,
        "audit_receipt_sha256": "6" * 64,
        "audit_public_log_sha256": "8" * 64,
        "recovery_helper_sha256": control.RECOVERY_HELPER_SHA256,
    }
    monkeypatch.setattr(control, "_load_authorization", lambda *_args, **_kwargs: (authorization, auth_value))

    class FakeRecoveryError(Exception):
        pass

    helper = SimpleNamespace(RecoveryError=FakeRecoveryError)
    monkeypatch.setattr(control, "_load_helper", lambda _bound: helper)
    monkeypatch.setattr(
        control,
        "_root_observation",
        lambda *_args, **_kwargs: ({"state": "present"}, "7" * 64, None, 10, -1, 12, -1),
    )
    monkeypatch.setattr(control, "_close_observation", lambda *_args: None)
    monkeypatch.setattr(control, "_revalidate_observation", lambda *_args: None)
    monkeypatch.setattr(control, "_revalidate_quarantined_root", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(control, "_enter_terminal_boundary", lambda: None)
    monkeypatch.setattr(control, "_commit_publication", lambda *_args: pytest.fail("drift must not publish"))
    monkeypatch.setattr(
        control.os,
        "environ",
        {
            "VMVM_V4_RECOVERY_CONTROL_SHA256": "1" * 64,
            "VMVM_V4_RECOVERY_CONTROL_FD": "3",
            "VMVM_V4_RECOVERY_HELPER_SHA256": control.RECOVERY_HELPER_SHA256,
            "VMVM_V4_RECOVERY_HELPER_FD": "4",
            "VMVM_V4_RECOVERY_MANIFEST_SHA256": "4" * 64,
            "VMVM_V4_RECOVERY_AUTH_FD": "5",
            "VMVM_V4_RECOVERY_RECEIPT_PATH": str(control.RECOVERY_RECEIPT),
        },
    )
    with pytest.raises(control.ControlError, match="root_state"):
        control.node_stage("recover")


def _patch_node_boundary(control, monkeypatch: pytest.MonkeyPatch, stage: str, auth_value: dict[str, object]):
    monkeypatch.setattr(control, "_validate_node_environment", lambda _stage: None)
    monkeypatch.setattr(
        control,
        "FD_RE",
        SimpleNamespace(fullmatch=lambda _value: SimpleNamespace(group=lambda _index: "3")),
    )
    monkeypatch.setattr(
        control,
        "_fd_from_env",
        lambda name, **_kwargs: bound(
            control,
            digest_value=control.RECOVERY_HELPER_SHA256 if "HELPER" in name else "1" * 64,
        ),
    )
    monkeypatch.setattr(
        control,
        "_load_authorization",
        lambda *_args, **_kwargs: (bound(control, digest_value="3" * 64), auth_value),
    )
    monkeypatch.setattr(control, "_close_observation", lambda *_args: None)
    monkeypatch.setattr(control, "_revalidate_observation", lambda *_args: None)
    monkeypatch.setattr(control, "_revalidate_quarantined_root", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(control, "_enter_terminal_boundary", lambda: None)
    monkeypatch.setattr(control.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        control.os,
        "environ",
        {
            "VMVM_V4_RECOVERY_CONTROL_SHA256": "1" * 64,
            "VMVM_V4_RECOVERY_CONTROL_FD": "3",
            "VMVM_V4_RECOVERY_HELPER_SHA256": control.RECOVERY_HELPER_SHA256,
            "VMVM_V4_RECOVERY_HELPER_FD": "4",
            "VMVM_V4_RECOVERY_MANIFEST_SHA256": "4" * 64,
            "VMVM_V4_RECOVERY_AUTH_FD": "5",
            "VMVM_V4_RECOVERY_RECEIPT_PATH": str(
                control.AUDIT_RECEIPT if stage == "audit" else control.RECOVERY_RECEIPT
            ),
            "SLURM_JOB_ID": "12",
        },
    )


def test_node_audit_publishes_bound_observation_without_mutating(monkeypatch: pytest.MonkeyPatch) -> None:
    control = load("controls_node_audit", "control.py")
    auth_value = control._authorization_common("audit", "4" * 64, "5" * 64, bundle_files(control))
    _patch_node_boundary(control, monkeypatch, "audit", auth_value)

    class FakeRecoveryError(Exception):
        pass

    helper = SimpleNamespace(
        RecoveryError=FakeRecoveryError,
        _quiesce=lambda *_args: pytest.fail("audit must not quiesce"),
        _quarantine_root_verified=lambda *_args: pytest.fail("audit must not quarantine"),
    )
    monkeypatch.setattr(control, "_load_helper", lambda _bound: helper)
    monkeypatch.setattr(
        control,
        "_root_observation",
        lambda *_args, **_kwargs: (
            {"state": "absent"},
            control.digest(control.canonical([])),
            None,
            10,
            -1,
            12,
            -1,
        ),
    )
    captured = {}
    order = []
    monkeypatch.setattr(control, "_enter_terminal_boundary", lambda: order.append("block"))
    monkeypatch.setattr(control, "_revalidate_observation", lambda *_args: order.append("revalidate"))

    def publish(action, path, value):
        order.append("publish")
        captured.update(action=action, path=path, value=value)

    monkeypatch.setattr(control, "_commit_publication", publish)
    control.node_stage("audit")
    assert order == ["block", "revalidate", "publish"]
    assert captured["action"] == "node-audit"
    assert captured["value"]["quiescence"] == {"observations": 2, "state": "absent"}
    assert captured["value"]["quarantine"] == {"state": "absent"}
    assert captured["value"]["root"] == {"state": "absent"}


def test_node_recovery_reproves_then_uses_exact_helper_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    control = load("controls_node_recover", "control.py")
    identity = {"device": 1, "inode": 2, "mode": 0o700, "mount_id": 3, "owner_uid": control.OWNER_UID}
    root = {"identity": identity, "inventory_class": "empty", "state": "present"}
    audit = {"root": root, "inventory_sha256": "7" * 64}
    auth_value = control._authorization_common("recover", "4" * 64, "5" * 64, bundle_files(control)) | {
        "audit_receipt": audit,
        "audit_receipt_sha256": "6" * 64,
        "audit_public_log_sha256": "8" * 64,
    }
    _patch_node_boundary(control, monkeypatch, "recover", auth_value)

    class FakeRecoveryError(Exception):
        pass

    inventory = SimpleNamespace(entries={}, identities=set())
    calls = []
    pending = False

    def quarantine(*_args) -> None:
        nonlocal pending
        calls.append("quarantine")
        pending = True

    helper = SimpleNamespace(
        RecoveryError=FakeRecoveryError,
        _quiesce=lambda *_args: calls.append("quiesce") or True,
        _quarantine_root_verified=quarantine,
        descriptor_identity=lambda _fd: identity,
    )
    monkeypatch.setattr(control, "_load_helper", lambda _bound: helper)
    parent_watch_fd = os.open("/dev/null", os.O_RDONLY)
    root_watch_fd = os.open("/dev/null", os.O_RDONLY)
    final_watch_fds = []

    def open_watch(_fd):
        descriptor = os.open("/dev/null", os.O_RDONLY)
        final_watch_fds.append(descriptor)
        return descriptor

    monkeypatch.setattr(
        control,
        "_root_observation",
        lambda *_args, **_kwargs: (
            root,
            "7" * 64,
            inventory,
            10,
            11,
            parent_watch_fd,
            root_watch_fd,
        ),
    )
    monkeypatch.setattr(helper, "_open_watch", open_watch, raising=False)
    monkeypatch.setattr(control.os, "listdir", lambda _fd: [])
    captured = {}
    monkeypatch.setattr(control.signal, "pthread_sigmask", lambda *_args: None)
    monkeypatch.setattr(control.signal, "sigpending", lambda: {signal.SIGTERM} if pending else set())

    def boundary() -> None:
        if control.signal.sigpending() & control.HANDLED_SIGNALS:
            raise control.Interrupted()

    monkeypatch.setattr(control, "_enter_terminal_boundary", boundary)
    monkeypatch.setattr(
        control,
        "publish_exclusive",
        lambda path, value: captured.update(path=path, value=value) or "9" * 64,
    )
    try:
        control.node_stage("recover")
    finally:
        for descriptor in final_watch_fds:
            os.close(descriptor)
    assert calls == ["quiesce", "quarantine"]
    assert captured["value"]["root_before"] == root
    assert captured["value"]["root_after"] == {"identity": identity, "state": "quarantined"}
    assert captured["value"]["state"] == "quarantined"
    assert control._COMMITTED_ACTION == "node-recover"


def test_node_recovery_finalizes_exact_quarantine_after_postrename_baseexception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control = load("controls_node_recover_resume", "control.py")
    identity = {"device": 1, "inode": 2, "mode": 0o700, "mount_id": 3, "owner_uid": control.OWNER_UID}
    audit_root = {"identity": identity, "inventory_class": "empty", "state": "present"}
    audit = {"root": audit_root, "inventory_sha256": "7" * 64}
    auth_value = control._authorization_common("recover", "4" * 64, "5" * 64, bundle_files(control)) | {
        "audit_receipt": audit,
        "audit_receipt_sha256": "6" * 64,
        "audit_public_log_sha256": "8" * 64,
    }
    _patch_node_boundary(control, monkeypatch, "recover", auth_value)
    monkeypatch.setattr(control.signal, "pthread_sigmask", lambda *_args: None)
    monkeypatch.setattr(control.signal, "sigpending", lambda: set())

    class FakeRecoveryError(Exception):
        pass

    inventory = SimpleNamespace(entries={}, identities=set())
    observations = iter(
        (
            (audit_root, "7" * 64, inventory, 10, 11, 12, 13),
            ({**audit_root, "state": "quarantined"}, "7" * 64, inventory, 20, 21, 22, 23),
        )
    )
    observation_arguments = []

    def observe(*_args, **kwargs):
        observation_arguments.append(kwargs)
        return next(observations)

    helper = SimpleNamespace(
        RecoveryError=FakeRecoveryError,
        _quiesce=lambda *_args: True,
        _quarantine_root_verified=lambda *_args: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    monkeypatch.setattr(control, "_load_helper", lambda _bound: helper)
    monkeypatch.setattr(control, "_root_observation", observe)
    published = {}
    monkeypatch.setattr(
        control,
        "publish_exclusive",
        lambda path, value: published.update(path=path, value=value) or "9" * 64,
    )

    control.node_stage("recover")

    assert len(observation_arguments) == 2
    assert all(item["authorized_quarantine"] == (audit_root, "7" * 64) for item in observation_arguments)
    assert published["value"]["root_before"] == audit_root
    assert published["value"]["root_after"] == {"identity": identity, "state": "quarantined"}
    assert control._COMMITTED_ACTION == "node-recover"


def test_batch_binder_uses_nofollow_retained_fds_and_clean_env() -> None:
    raw = (HERE / "run_stage.sbatch").read_text()
    assert "os.O_NOFOLLOW" in raw
    assert "os.set_inheritable" in raw
    assert '"/proc/self/fd/3"' in raw
    assert "os.execve" in raw
    assert "allowed = {" in raw
    assert "--export=NONE" not in raw
    assert "X2P_PROXY_URL" not in raw


def test_recovery_authorization_schema_rejects_unbound_audit_receipt() -> None:
    control = load("controls_audit_value", "control.py")
    value = {
        "artifact_type": "vmvm_v4_scratch_recovery_audit_receipt_v1",
        "audit_authorization_sha256": "1" * 64,
        "candidate_token": control.TOKEN,
        "inventory_sha256": control.digest(control.canonical([])),
        "job": {
            "cluster": control.CLUSTER,
            "job_id": "12",
            "job_name": control.AUDIT_JOB_NAME,
            "node": control.TARGET_NODE,
        },
        "quiescence": {"observations": 1, "state": "absent"},
        "root": {"state": "absent"},
        "schema_version": 1,
        "state": "audited",
    }
    with pytest.raises(control.ControlError, match="binding"):
        control._validate_audit_value(value)


def test_freezer_manifest_binds_reviewed_source_and_helper() -> None:
    freezer = load("controls_freezer", "freeze_controls.py")
    payloads = {name: name.encode() for name in freezer.FILES}
    payloads["recover_vmvm_owner_lifecycle_v4_scratch.py"] = b"helper"
    value = freezer.manifest("1" * 40, "2" * 40, "3" * 40, payloads)
    assert value["control_source_commit"] == "1" * 40
    assert value["control_source_tree"] == "2" * 40
    assert value["control_source_subtree"] == "3" * 40
    assert value["recovery_subtree"] == freezer.RECOVERY_SUBTREE
    assert value["files"]["control.py"]["mode"] == "0500"


def test_freezer_install_is_exclusive_and_seals_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    freezer = load("controls_freezer_install", "freeze_controls.py")
    destination = tmp_path / "bundle"
    monkeypatch.setattr(freezer, "DESTINATION", destination)
    payloads = {name: (name + "\n").encode() for name in freezer.FILES}
    value = freezer.manifest("1" * 40, "2" * 40, "3" * 40, payloads)
    freezer.install(payloads, value)
    assert stat.S_IMODE(destination.stat().st_mode) == 0o555
    assert stat.S_IMODE((destination / "control.py").stat().st_mode) == 0o500
    assert stat.S_IMODE((destination / "manifest.json").stat().st_mode) == 0o400
    with pytest.raises(freezer.FreezeError, match="freshness"):
        freezer.install(payloads, value)


def test_source_has_no_task_model_or_credential_access_surface() -> None:
    source = (HERE / "control.py").read_text()
    forbidden = ("datasets/", "tasks/", "OPENAI_API_KEY]", "X2P_PROXY_URL]", "requests.", "urllib.")
    assert not any(value in source for value in forbidden)


def test_readme_marks_candidate_inert_and_orders_audit_before_recovery() -> None:
    raw = (HERE / "README.md").read_text()
    assert "source-only, inert" in raw
    assert "Status: **HOLD**" in raw
    assert raw.index("`control.py preflight`") < raw.index("`authorize-audit`") < raw.index("`authorize-recover`")
