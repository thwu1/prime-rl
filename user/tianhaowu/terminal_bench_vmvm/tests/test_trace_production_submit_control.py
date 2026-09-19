from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import signal
import stat
from pathlib import Path
from typing import Any

import pytest
import trace_production_bootstrap as bootstrap
import trace_production_submit_control as submit


class Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


def _phase(*, state: str, timeout: int) -> dict[str, Any]:
    return {
        "converged": True,
        "elapsed_milliseconds": 2_000,
        "explicit_conflict_fields": [],
        "final_mismatch_fields": [],
        "mismatch_fields": [],
        "mismatch_occurrences": {},
        "polls": 2,
        "required_consecutive": 2,
        "state": state,
        "timeout_seconds": timeout,
    }


def _authorization(tmp_path: Path) -> dict[str, Any]:
    nonce = "0123456789abcdef" * 4
    return {
        "authorization_nonce": nonce,
        "run": {"path": str(tmp_path / "run")},
        "source": {
            "project_root": str(tmp_path / "source"),
            "artifacts": {
                "production_audit_wrapper": {
                    "path": str(
                        tmp_path
                        / "source/user/tianhaowu/terminal_bench_vmvm/run_trace_production_audit.sbatch"
                    ),
                    "sha256": "a" * 64,
                }
            },
        },
        "audit_submission": {
            "cluster": "test-cluster",
            "job_name": "trace-production-audit-0123456789abcdef",
            "launch_token_sha256": hashlib.sha256(nonce.encode()).hexdigest(),
            "log_path": str(tmp_path / "audit_%j.log"),
            "reservation_dir": str(tmp_path / "reservation"),
            "policy": {
                "held_submission": True,
                "one_shot": True,
                "requeue": False,
                "wrapper_transport": "sbatch_stdin_exact_bytes",
            },
            "resources": {
                "account": "ram",
                "cpus_per_task": 2,
                "memory": "8G",
                "nodes": 1,
                "ntasks": 1,
                "partition": "cpu_x86",
                "qos": "cpu_x86_lowest",
                "time_limit": "02:00:00",
            },
        },
    }


def test_sbatch_uses_hold_and_exact_stdin_wrapper_transport(tmp_path: Path) -> None:
    command = submit._sbatch_command(_authorization(tmp_path), ["arg-one", "arg-two"])

    assert command[0] == "/usr/bin/sbatch"
    assert command.count("--hold") == 1
    assert command.count("--no-requeue") == 1
    assert command.count("--export=NONE") == 1
    assert command[-3:] == ["-", "arg-one", "arg-two"]
    assert not any(item.endswith(".sbatch") for item in command)
    assert (
        submit._job_expectations(_authorization(tmp_path), "123")["Command"] == "(null)"
    )


def test_poll_phase_spans_more_than_twelve_transient_views(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def snapshot(*_args: object, **_kwargs: object) -> tuple[set[str], set[str], str]:
        nonlocal calls
        calls += 1
        if calls <= 14:
            return {"accounting_cardinality"}, set(), "PENDING"
        return set(), set(), "PENDING"

    monkeypatch.setattr(submit, "scheduler_snapshot", snapshot)
    clock = Clock()
    result = submit.poll_phase(
        _authorization(tmp_path),
        "123",
        held=True,
        timeout=60,
        runner=lambda _argv, _timeout: submit.CommandResult(0, b"", b""),
        sleeper=clock.sleep,
        clock=clock,
    )

    assert result["converged"] is True
    assert result["polls"] == 16
    assert clock.value == 30


def test_phase_queries_are_capped_by_one_shared_deadline(
    tmp_path: Path,
) -> None:
    clock = Clock()
    observed_timeouts: list[float] = []

    def runner(
        _argv: list[str] | tuple[str, ...], timeout: float
    ) -> submit.CommandResult:
        observed_timeouts.append(timeout)
        clock.value += 19.5
        return submit.CommandResult(1, b"", b"")

    result = submit.poll_phase(
        _authorization(tmp_path),
        "123",
        held=True,
        timeout=20,
        runner=runner,
        sleeper=clock.sleep,
        clock=clock,
    )
    assert result["converged"] is False
    assert result["polls"] == 1
    assert observed_timeouts == [20.0]
    assert result["elapsed_milliseconds"] == 20_000


def test_explicit_conflict_is_monotonic_and_stops_phase_poll(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def snapshot(*_args: object, **_kwargs: object) -> tuple[set[str], set[str], str]:
        nonlocal calls
        calls += 1
        return {"Command"}, {"Command"}, "PENDING"

    monkeypatch.setattr(submit, "scheduler_snapshot", snapshot)
    result = submit.poll_phase(
        _authorization(tmp_path),
        "123",
        held=True,
        timeout=60,
        runner=lambda _argv, _timeout: submit.CommandResult(0, b"", b""),
        sleeper=lambda _seconds: None,
        clock=Clock(),
    )

    assert calls == 1
    assert result["converged"] is False
    assert result["explicit_conflict_fields"] == ["Command"]


def test_phase_conflict_latch_survives_base_exception_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    latch: set[str] = set()

    def snapshot(*_args: object, **kwargs: object) -> tuple[set[str], set[str], str]:
        observed_latch = kwargs["conflict_latch"]
        assert isinstance(observed_latch, set)
        observed_latch.add("UserId")
        raise submit.SubmissionInterrupted

    monkeypatch.setattr(submit, "scheduler_snapshot", snapshot)
    with pytest.raises(submit.SubmissionInterrupted):
        submit.poll_phase(
            _authorization(tmp_path),
            "123",
            held=True,
            timeout=60,
            runner=lambda _argv, _timeout: submit.CommandResult(0, b"", b""),
            sleeper=lambda _seconds: None,
            clock=Clock(),
            conflict_latch=latch,
        )
    assert latch == {"UserId"}


def test_cancel_conflict_never_issues_control(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        submit,
        "_precontrol_identity",
        lambda *_args, **_kwargs: ("conflict", ("UserId",)),
    )

    def runner(
        argv: list[str] | tuple[str, ...], _timeout: float
    ) -> submit.CommandResult:
        controls.append(tuple(argv))
        return submit.CommandResult(0, b"", b"")

    with pytest.raises(
        submit.LifecycleError, match="^cancellation_unconfirmed$"
    ) as raised:
        submit.cancel_and_prove(
            _authorization(tmp_path),
            "123",
            direct_provenance=True,
            runner=runner,
            sleeper=lambda _seconds: None,
            clock=Clock(),
        )
    assert raised.value.evidence["cancel_attempts"] == 0
    assert controls == []


def test_direct_candidate_gets_one_exact_cancel_when_identity_stays_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        submit,
        "_precontrol_identity",
        lambda *_args, **_kwargs: ("unavailable", ()),
    )
    monkeypatch.setattr(
        submit,
        "_terminal_snapshot",
        lambda *_args, **_kwargs: ("unavailable", "UNKNOWN", "", ()),
    )

    def runner(
        argv: list[str] | tuple[str, ...], _timeout: float
    ) -> submit.CommandResult:
        controls.append(tuple(argv))
        return submit.CommandResult(0, b"", b"")

    clock = Clock()
    with pytest.raises(
        submit.LifecycleError, match="^cancellation_unconfirmed$"
    ) as raised:
        submit.cancel_and_prove(
            _authorization(tmp_path),
            "123",
            direct_provenance=True,
            runner=runner,
            sleeper=clock.sleep,
            clock=clock,
        )
    scancel = [argv for argv in controls if argv and argv[0] == "/usr/bin/scancel"]
    assert scancel == [("/usr/bin/scancel", "-M", "test-cluster", "123")]
    assert raised.value.evidence["cancel_attempts"] == 1


def test_name_exclusivity_requires_six_exact_views(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations = iter([["123"], ["123", "124"], *[["123"]] * 6])
    monkeypatch.setattr(
        submit,
        "scheduler_name_matches",
        lambda *_args, **_kwargs: next(observations),
    )
    clock = Clock()
    result = submit._prove_name_exclusive(
        _authorization(tmp_path),
        "123",
        runner=lambda _argv, _timeout: submit.CommandResult(0, b"", b""),
        sleeper=clock.sleep,
        clock=clock,
    )
    assert result == {"consecutive": 6, "polls": 8}


def test_cancellation_terminal_proof_converges_after_more_than_twelve_polls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        submit,
        "_precontrol_identity",
        lambda *_args, **_kwargs: ("exact", ()),
    )
    snapshots = 0

    def terminal(*_args: object, **_kwargs: object):
        nonlocal snapshots
        snapshots += 1
        if snapshots <= 15:
            return "active", "RUNNING", "", ()
        return "terminal", "CANCELLED", "stable", ()

    monkeypatch.setattr(submit, "_terminal_snapshot", terminal)
    monkeypatch.setattr(
        submit,
        "scheduler_name_matches",
        lambda *_args, **_kwargs: ["123"],
    )
    controls: list[tuple[str, ...]] = []

    def runner(
        argv: list[str] | tuple[str, ...], _timeout: float
    ) -> submit.CommandResult:
        controls.append(tuple(argv))
        return submit.CommandResult(0, b"", b"")

    clock = Clock()
    result = submit.cancel_and_prove(
        _authorization(tmp_path),
        "123",
        direct_provenance=True,
        runner=runner,
        sleeper=clock.sleep,
        clock=clock,
    )
    assert [item for item in controls if item[0] == "/usr/bin/scancel"] == [
        ("/usr/bin/scancel", "-M", "test-cluster", "123")
    ]
    assert result["terminal_polls"] == 20
    assert result["terminal_consecutive"] == 6
    assert result["name_exclusivity"] == {"consecutive": 6, "polls": 6}


def test_partial_phase_failure_retains_prior_explicit_conflict(
    tmp_path: Path,
) -> None:
    authorization = _authorization(tmp_path)
    expected = submit._job_expectations(authorization, "123")
    scontrol = {
        **expected,
        "JobName": "conflicting-name",
        "JobState": "PENDING",
        "Reason": "JobHeldUser",
        "Priority": "0",
        "StartTime": "Unknown",
        "NumNodes": "1-1",
        "NodeList": "",
        "BatchHost": "(null)",
    }
    raw = " ".join(f"{key}={value}" for key, value in scontrol.items()).encode()
    calls = 0

    def runner(
        _argv: list[str] | tuple[str, ...], _timeout: float
    ) -> submit.CommandResult:
        nonlocal calls
        calls += 1
        if calls == 1:
            return submit.CommandResult(0, raw, b"")
        return submit.CommandResult(1, b"", b"")

    latch: set[str] = set()
    with pytest.raises(submit.SchedulerObservationError) as raised:
        submit.scheduler_snapshot(
            authorization,
            "123",
            held=True,
            runner=runner,
            conflict_latch=latch,
        )
    assert raised.value.conflicts == ("JobName",)
    assert latch == {"JobName"}


def test_terminal_partial_failure_retains_queue_conflict_and_forbids_cancel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _authorization(tmp_path)
    expected = submit._job_expectations(authorization, "123")
    expected.update(
        {
            "JobState": "PENDING",
            "Reason": "Priority",
            "Priority": "1",
            "StartTime": "Unknown",
            "NumNodes": "1",
            "NodeList": "",
            "BatchHost": "(null)",
        }
    )
    raw = " ".join(f"{key}={value}" for key, value in expected.items()).encode()
    calls = 0
    controls: list[tuple[str, ...]] = []

    def runner(
        argv: list[str] | tuple[str, ...], _timeout: float
    ) -> submit.CommandResult:
        nonlocal calls
        calls += 1
        if argv[0] == "/usr/bin/scancel":
            controls.append(tuple(argv))
            return submit.CommandResult(0, b"", b"")
        if calls == 1:
            return submit.CommandResult(0, raw, b"")
        if calls == 2:
            return submit.CommandResult(0, b"123|wrong-name|tianhaowu|PENDING\n", b"")
        return submit.CommandResult(1, b"", b"")

    latch: set[str] = set()
    status = submit._terminal_snapshot(
        authorization,
        "123",
        runner=runner,
        conflict_latch=latch,
    )
    assert status[0] == "conflict"
    assert status[3] == ("JobName",)
    assert latch == {"JobName"}

    monkeypatch.setattr(
        submit,
        "_precontrol_identity",
        lambda *_args, **_kwargs: ("unavailable", ()),
    )
    with pytest.raises(
        submit.LifecycleError, match="^cancellation_unconfirmed$"
    ) as raised:
        submit.cancel_and_prove(
            authorization,
            "123",
            direct_provenance=True,
            runner=runner,
            sleeper=lambda _seconds: None,
            clock=Clock(),
            conflict_latch=latch,
        )
    assert raised.value.evidence["cancel_attempts"] == 0
    assert controls == []


def test_invoke_sbatch_reaps_process_group_on_base_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[object] = []

    class Process:
        pid = 4321
        returncode = -int(signal.SIGTERM)
        calls = 0

        def communicate(self, **_kwargs: object) -> tuple[bytes, bytes]:
            self.calls += 1
            if self.calls == 1:
                raise KeyboardInterrupt
            return b"", b""

        def poll(self) -> int | None:
            return None if self.calls == 1 else self.returncode

    monkeypatch.setattr(submit.subprocess, "Popen", lambda *_args, **_kwargs: Process())
    monkeypatch.setattr(submit.os, "killpg", lambda pid, sig: events.append((pid, sig)))
    monkeypatch.setattr(
        submit,
        "_prove_process_group_empty",
        lambda process_group: events.append(("proved", process_group)),
    )
    with pytest.raises(KeyboardInterrupt):
        submit.invoke_sbatch(
            ["/usr/bin/sbatch", "-"],
            b"#!/usr/bin/bash\n",
            {"PATH": "/usr/bin:/bin"},
        )
    assert events == [(4321, signal.SIGTERM), ("proved", 4321)]


def test_reservation_anchor_rejects_name_replacement_between_publications(
    tmp_path: Path,
) -> None:
    reservation = tmp_path / "reservation"
    anchor = submit.create_reservation(reservation)
    displaced = tmp_path / "displaced"
    try:
        submit.publish_once(anchor, "launch_intent.json", b"intent\n")
        reservation.rename(displaced)
        reservation.mkdir(mode=0o700)

        with pytest.raises(submit.SubmissionError, match="^reservation_changed$"):
            submit.publish_once(anchor, "held_authorization.json", b"held\n")
        assert list(reservation.iterdir()) == []
        assert {path.name for path in displaced.iterdir()} == {"launch_intent.json"}
    finally:
        anchor.close()


def test_reservation_anchor_rejects_parent_replacement_between_phases(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "parent"
    parent.mkdir(mode=0o700)
    reservation = parent / "reservation"
    anchor = submit.create_reservation(reservation)
    displaced = tmp_path / "displaced"
    try:
        submit.publish_once(anchor, "launch_intent.json", b"intent\n")
        parent.rename(displaced)
        parent.mkdir(mode=0o700)
        replacement = parent / "reservation"
        replacement.mkdir(mode=0o700)

        with pytest.raises(submit.SubmissionError, match="^reservation_changed$"):
            anchor.revalidate(expected_mode=0o700)
        assert list(replacement.iterdir()) == []
        assert {path.name for path in (displaced / "reservation").iterdir()} == {
            "launch_intent.json"
        }
    finally:
        anchor.close()


def test_success_publication_rolls_back_partial_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reservation = tmp_path / "reservation"
    anchor = submit.create_reservation(reservation)
    for name in ("held_authorization.json", "launch_intent.json"):
        path = reservation / name
        path.write_bytes(b"{}\n")
        path.chmod(0o400)
    original = submit.publish_once
    calls = 0

    def fail_second(
        observed_anchor: submit.ReservationAnchor,
        name: str,
        raw: bytes,
        mode: int = 0o400,
    ) -> str:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise submit.SubmissionError("injected_publication_failure")
        return original(observed_anchor, name, raw, mode)

    monkeypatch.setattr(submit, "publish_once", fail_second)
    committed = {"value": False}
    try:
        with pytest.raises(
            submit.SubmissionError, match="^injected_publication_failure$"
        ):
            submit._publish_success(anchor, b"receipt\n", b"permit\n", committed)
        assert committed == {"value": False}
        assert stat.S_IMODE(reservation.stat().st_mode) == 0o700
        assert {path.name for path in reservation.iterdir()} == {
            "held_authorization.json",
            "launch_intent.json",
        }
    finally:
        anchor.close()


def test_success_publication_never_rolls_back_after_admission_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reservation = tmp_path / "reservation"
    anchor = submit.create_reservation(reservation)
    for name in ("held_authorization.json", "launch_intent.json"):
        path = reservation / name
        path.write_bytes(b"{}\n")
        path.chmod(0o400)

    def ambiguous_commit(
        observed_anchor: submit.ReservationAnchor,
        committed: dict[str, bool],
    ) -> None:
        os.fchmod(observed_anchor.descriptor, 0o500)
        committed["value"] = True
        raise submit.LifecycleError("reservation_commit_ambiguous")

    monkeypatch.setattr(submit, "_seal_reservation", ambiguous_commit)
    committed = {"value": False}
    try:
        with pytest.raises(
            submit.LifecycleError,
            match="^reservation_commit_ambiguous$",
        ):
            submit._publish_success(anchor, b"receipt\n", b"permit\n", committed)
        assert committed == {"value": True}
        assert stat.S_IMODE(reservation.stat().st_mode) == 0o500
        assert {path.name for path in reservation.iterdir()} == {
            "activation_permit.json",
            "held_authorization.json",
            "launch_intent.json",
            "submission_receipt.json",
        }
    finally:
        anchor.close()


def test_untrusted_exception_text_never_becomes_failure_code() -> None:
    assert (
        submit._safe_exception_code(RuntimeError("looks_safe")) == "submission_failed"
    )
    assert (
        submit._safe_exception_code(submit.SubmissionError("known_safe"))
        == "known_safe"
    )


def test_sealed_submitter_descriptor_cannot_be_rewritten() -> None:
    body = b"#!/usr/bin/bash\nexit 0\n"
    descriptor = os.memfd_create("sealed-submitter-test", os.MFD_ALLOW_SEALING)
    try:
        os.write(descriptor, body)
        seals = (
            fcntl.F_SEAL_SEAL
            | fcntl.F_SEAL_SHRINK
            | fcntl.F_SEAL_GROW
            | fcntl.F_SEAL_WRITE
        )
        fcntl.fcntl(descriptor, fcntl.F_ADD_SEALS, seals)
        assert (
            submit._descriptor_bytes(
                descriptor,
                hashlib.sha256(body).hexdigest(),
                sealed=True,
            )
            == body
        )
        with pytest.raises(PermissionError):
            os.pwrite(descriptor, b"x", 0)
    finally:
        os.close(descriptor)


def test_reservation_commit_flag_is_set_at_admission_before_postcommit_fsync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "reservation"
    anchor = submit.create_reservation(root)
    committed = {"value": False}
    original = submit.os.fsync
    calls = 0

    def fail_before_commit(descriptor: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected")
        original(descriptor)

    monkeypatch.setattr(submit.os, "fsync", fail_before_commit)
    try:
        with pytest.raises(
            submit.LifecycleError, match="^reservation_commit_ambiguous$"
        ):
            submit._seal_reservation(anchor, committed)
        assert committed["value"] is True
        assert stat.S_IMODE(root.stat().st_mode) == 0o500
    finally:
        anchor.close()


def test_wrapper_gate_exceeds_release_activation_and_publication_bounds() -> None:
    wrapper = (
        Path(submit.__file__).with_name("run_trace_production_audit.sbatch").read_text()
    )
    assert "SECONDS + 900" in wrapper
    assert 900 > submit.QUERY_TIMEOUT_SECONDS + submit.ACTIVATION_TIMEOUT_SECONDS + 30
    assert bootstrap.HELD_TIMEOUT_SECONDS == submit.HELD_TIMEOUT_SECONDS
    assert bootstrap.FINAL_HELD_TIMEOUT_SECONDS == submit.QUERY_TIMEOUT_SECONDS * 2
    assert bootstrap.ACTIVATION_TIMEOUT_SECONDS == submit.ACTIVATION_TIMEOUT_SECONDS


def test_submit_is_one_shot_held_release_then_sealed_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _authorization(tmp_path)
    wrapper = b"#!/usr/bin/bash\nexit 0\n"
    wrapper_sha = hashlib.sha256(wrapper).hexdigest()
    authorization["source"]["artifacts"]["production_audit_wrapper"]["sha256"] = (
        wrapper_sha
    )
    (tmp_path / "run").mkdir()
    wrapper_path = (
        tmp_path
        / "source/user/tianhaowu/terminal_bench_vmvm/run_trace_production_audit.sbatch"
    )
    wrapper_path.parent.mkdir(parents=True)
    wrapper_path.write_bytes(wrapper)
    wrapper_path.chmod(0o644)
    monkeypatch.setattr(submit, "load_authorization", lambda *_args: authorization)
    monkeypatch.setattr(submit, "validate_python", lambda *_args: None)
    monkeypatch.setattr(submit, "validate_source", lambda *_args: {"source": "a" * 64})
    monkeypatch.setattr(submit, "stable_bytes", lambda *_args, **_kwargs: wrapper)
    monkeypatch.setattr(submit, "scheduler_name_matches", lambda *_args: [])
    monkeypatch.setattr(
        submit,
        "resolve_submission",
        lambda *_args, **_kwargs: ("123", True, {"polls": 1, "zero_rounds": 0}),
    )
    phases = iter(
        [
            _phase(state="PENDING", timeout=submit.HELD_TIMEOUT_SECONDS),
            _phase(state="PENDING", timeout=submit.QUERY_TIMEOUT_SECONDS * 2),
            _phase(state="PENDING", timeout=submit.QUERY_TIMEOUT_SECONDS * 2),
            _phase(state="RUNNING", timeout=submit.ACTIVATION_TIMEOUT_SECONDS),
        ]
    )
    monkeypatch.setattr(submit, "poll_phase", lambda *_args, **_kwargs: next(phases))
    monkeypatch.setattr(
        submit, "_precontrol_identity", lambda *_args, **_kwargs: ("exact", ())
    )
    sbatch_calls: list[tuple[list[str], bytes]] = []
    release_calls: list[tuple[str, ...]] = []

    def sbatch_invoker(command, body, _environment):
        sbatch_calls.append((list(command), body))
        return "completed", 0, b"123;test-cluster\n"

    def runner(argv, _timeout):
        release_calls.append(tuple(argv))
        return submit.CommandResult(0, b"", b"")

    result = submit.submit(
        tmp_path / "authorization.json",
        "b" * 64,
        wrapper,
        wrapper_sha,
        Path("/usr/bin/python3.12"),
        "c" * 64,
        ["batch-arg"],
        "/synthetic/cert",
        "/synthetic/key",
        runner=runner,
        sbatch_invoker=sbatch_invoker,
    )

    reservation = tmp_path / "reservation"
    assert result["state"] == "submitted"
    assert len(sbatch_calls) == 1 and sbatch_calls[0][1] == wrapper
    assert sbatch_calls[0][0][-6:-4] == ["-", "batch-arg"]
    assert release_calls == [
        ("/usr/bin/scontrol", "-M", "test-cluster", "release", "123")
    ]
    assert stat.S_IMODE(reservation.stat().st_mode) == 0o500
    assert {path.name for path in reservation.iterdir()} == {
        "activation_permit.json",
        "held_authorization.json",
        "launch_intent.json",
        "submission_receipt.json",
    }
    intent = json.loads((reservation / "launch_intent.json").read_bytes())
    reservation_identity = intent["reservation_identity"]
    for name, artifact_type in (
        ("launch_intent.json", submit.INTENT_TYPE),
        ("held_authorization.json", submit.HELD_AUTHORIZATION_TYPE),
        ("submission_receipt.json", submit.RECEIPT_TYPE),
        ("activation_permit.json", submit.PERMIT_TYPE),
    ):
        record = json.loads((reservation / name).read_bytes())
        assert record["schema_version"] == submit.ADMISSION_SCHEMA_VERSION
        assert record["artifact_type"] == artifact_type
        assert record["reservation_identity"] == reservation_identity
    assert sbatch_calls[0][0][-4:] == [
        str(reservation_identity["device"]),
        str(reservation_identity["inode"]),
        str(reservation_identity["parent_device"]),
        str(reservation_identity["parent_inode"]),
    ]
    attestation = bootstrap.validate_submission_admission(
        tmp_path / "authorization.json",
        "b" * 64,
        authorization,
        reservation.resolve(),
        "123",
        authorization["audit_submission"]["job_name"],
        reservation_identity,
    )
    assert attestation["job"] == {
        "cluster": "test-cluster",
        "id": "123",
        "name": "trace-production-audit-0123456789abcdef",
    }
    with pytest.raises(
        bootstrap.BootstrapError, match="^submission_admission_invalid$"
    ):
        bootstrap.validate_submission_admission(
            tmp_path / "authorization.json",
            "b" * 64,
            authorization,
            reservation.resolve(),
            "123",
            authorization["audit_submission"]["job_name"],
            {**reservation_identity, "inode": reservation_identity["inode"] + 1},
        )
    displaced_admission = tmp_path / "displaced-admission"
    reservation.rename(displaced_admission)
    shutil.copytree(displaced_admission, reservation)
    with pytest.raises(
        bootstrap.BootstrapError, match="^submission_admission_invalid$"
    ):
        bootstrap.validate_submission_admission(
            tmp_path / "authorization.json",
            "b" * 64,
            authorization,
            reservation.resolve(),
            "123",
            authorization["audit_submission"]["job_name"],
            reservation_identity,
        )
    reservation.chmod(0o700)
    shutil.rmtree(reservation)
    displaced_admission.rename(reservation)
    reservation.chmod(0o700)
    receipt_path = reservation / "submission_receipt.json"
    receipt = json.loads(receipt_path.read_bytes())
    receipt.pop("submission_receipt_sha256")
    receipt["unexpected"] = True
    receipt_raw = submit._envelope(receipt, "submission_receipt_sha256")
    receipt_path.chmod(0o600)
    receipt_path.write_bytes(receipt_raw)
    receipt_path.chmod(0o400)
    permit_path = reservation / "activation_permit.json"
    permit = json.loads(permit_path.read_bytes())
    permit.pop("activation_permit_sha256")
    permit["submission_receipt"]["sha256"] = hashlib.sha256(receipt_raw).hexdigest()
    permit_raw = submit._envelope(permit, "activation_permit_sha256")
    permit_path.chmod(0o600)
    permit_path.write_bytes(permit_raw)
    permit_path.chmod(0o400)
    reservation.chmod(0o500)
    with pytest.raises(
        bootstrap.BootstrapError, match="^submission_admission_invalid$"
    ):
        bootstrap.validate_submission_admission(
            tmp_path / "authorization.json",
            "b" * 64,
            authorization,
            reservation.resolve(),
            "123",
            authorization["audit_submission"]["job_name"],
            reservation_identity,
        )


def test_submit_rejects_reservation_replacement_before_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _authorization(tmp_path)
    wrapper = b"#!/usr/bin/bash\nexit 0\n"
    wrapper_sha = hashlib.sha256(wrapper).hexdigest()
    authorization["source"]["artifacts"]["production_audit_wrapper"]["sha256"] = (
        wrapper_sha
    )
    (tmp_path / "run").mkdir()
    wrapper_path = (
        tmp_path
        / "source/user/tianhaowu/terminal_bench_vmvm/run_trace_production_audit.sbatch"
    )
    wrapper_path.parent.mkdir(parents=True)
    wrapper_path.write_bytes(wrapper)
    wrapper_path.chmod(0o644)
    monkeypatch.setattr(submit, "load_authorization", lambda *_args: authorization)
    monkeypatch.setattr(submit, "validate_python", lambda *_args: None)
    monkeypatch.setattr(submit, "validate_source", lambda *_args: {"source": "a" * 64})
    monkeypatch.setattr(submit, "stable_bytes", lambda *_args, **_kwargs: wrapper)
    monkeypatch.setattr(submit, "scheduler_name_matches", lambda *_args: [])
    monkeypatch.setattr(
        submit,
        "resolve_submission",
        lambda *_args, **_kwargs: ("123", True, {"polls": 1, "zero_rounds": 0}),
    )
    monkeypatch.setattr(
        submit, "_precontrol_identity", lambda *_args, **_kwargs: ("exact", ())
    )
    cancelled: list[str] = []

    def cancel(*_args: object, **_kwargs: object) -> dict[str, object]:
        cancelled.append("123")
        return {"confirmed": True}

    monkeypatch.setattr(submit, "cancel_and_prove", cancel)
    phases = 0
    reservation = tmp_path / "reservation"
    displaced = tmp_path / "displaced"

    def poll(*_args: object, **kwargs: object) -> dict[str, Any]:
        nonlocal phases
        phases += 1
        result = _phase(state="PENDING", timeout=int(kwargs["timeout"]))
        if phases == 3:
            reservation.rename(displaced)
            reservation.mkdir(mode=0o700)
        return result

    monkeypatch.setattr(submit, "poll_phase", poll)
    release_calls: list[tuple[str, ...]] = []

    def runner(argv, _timeout):
        release_calls.append(tuple(argv))
        return submit.CommandResult(0, b"", b"")

    with pytest.raises(submit.LifecycleError, match="^reservation_changed$"):
        submit.submit(
            tmp_path / "authorization.json",
            "b" * 64,
            wrapper,
            wrapper_sha,
            Path("/usr/bin/python3.12"),
            "c" * 64,
            ["batch-arg"],
            "/synthetic/cert",
            "/synthetic/key",
            runner=runner,
            sbatch_invoker=lambda *_args: ("completed", 0, b"123;test-cluster\n"),
        )

    assert cancelled == ["123"]
    assert release_calls == []
    assert list(reservation.iterdir()) == []
    assert {path.name for path in displaced.iterdir()} == {
        "held_authorization.json",
        "launch_intent.json",
    }


def test_interrupted_sbatch_reconciles_no_job_before_sealed_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _authorization(tmp_path)
    wrapper = b"#!/usr/bin/bash\nexit 0\n"
    wrapper_sha = hashlib.sha256(wrapper).hexdigest()
    authorization["source"]["artifacts"]["production_audit_wrapper"]["sha256"] = (
        wrapper_sha
    )
    (tmp_path / "run").mkdir()
    wrapper_path = (
        tmp_path
        / "source/user/tianhaowu/terminal_bench_vmvm/run_trace_production_audit.sbatch"
    )
    wrapper_path.parent.mkdir(parents=True)
    wrapper_path.write_bytes(wrapper)
    wrapper_path.chmod(0o644)
    monkeypatch.setattr(submit, "load_authorization", lambda *_args: authorization)
    monkeypatch.setattr(submit, "validate_python", lambda *_args: None)
    monkeypatch.setattr(submit, "validate_source", lambda *_args: {"source": "a" * 64})
    monkeypatch.setattr(submit, "stable_bytes", lambda *_args, **_kwargs: wrapper)
    monkeypatch.setattr(submit, "scheduler_name_matches", lambda *_args: [])
    reconciliations = 0

    def reconcile(*_args: object, **_kwargs: object):
        nonlocal reconciliations
        reconciliations += 1
        return None, False, {"polls": 6, "zero_rounds": 6}

    monkeypatch.setattr(submit, "resolve_submission", reconcile)

    def interrupted(*_args: object, **_kwargs: object):
        raise submit.SubmissionInterrupted

    with pytest.raises(submit.SubmissionInterrupted):
        submit.submit(
            tmp_path / "authorization.json",
            "b" * 64,
            wrapper,
            wrapper_sha,
            Path("/usr/bin/python3.12"),
            "c" * 64,
            ["batch-arg"],
            "/synthetic/cert",
            "/synthetic/key",
            runner=lambda _argv, _timeout: submit.CommandResult(0, b"", b""),
            sbatch_invoker=interrupted,
        )

    reservation = tmp_path / "reservation"
    assert reconciliations == 1
    assert stat.S_IMODE(reservation.stat().st_mode) == 0o500
    failure = json.loads((reservation / "submission_failure.json").read_bytes())
    reservation_status = reservation.stat(follow_symlinks=False)
    parent_status = reservation.parent.stat(follow_symlinks=False)
    assert failure["schema_version"] == submit.ADMISSION_SCHEMA_VERSION
    assert failure["artifact_type"] == submit.FAILURE_TYPE
    assert failure["reservation_identity"] == {
        "device": reservation_status.st_dev,
        "inode": reservation_status.st_ino,
        "owner_uid": os.getuid(),
        "parent_device": parent_status.st_dev,
        "parent_inode": parent_status.st_ino,
    }
    assert failure["code"] == "submission_interrupted"
    assert failure["cancellation"] == {
        "cancel_attempts": 0,
        "confirmed": True,
        "explicit_conflict_fields": [],
        "identity_status": "no_job_proved",
        "reason": "no_job_proved",
    }
