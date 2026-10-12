from __future__ import annotations

import ast
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import signal
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("registry_gate_v27_controller", HERE / "controller.py")
assert SPEC is not None and SPEC.loader is not None
controller = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = controller
SPEC.loader.exec_module(controller)


def held_record() -> dict[str, str]:
    job_id = "12345"
    token = "a" * 24
    return {
        "JobId": job_id,
        "JobName": controller.JOB_NAME,
        "UserId": controller.OWNER_RECORD,
        "Comment": f"{controller.COMMENT_PREFIX}{token}",
        "Command": "(null)",
        "WorkDir": str(controller.BUNDLE),
        "Account": controller.ACCOUNT,
        "QOS": controller.QOS,
        "Partition": controller.PARTITION,
        "ReqNodeList": controller.PINNED_NODE,
        "TimeLimit": controller.WALLTIME,
        "StdOut": str(controller.LOG_ROOT / f"slurm-{job_id}.log"),
        "StdErr": str(controller.LOG_ROOT / f"slurm-{job_id}.log"),
        "Requeue": "0",
        "Restarts": "0",
        "NumNodes": "1",
        "NumCPUs": "4",
        "ReqTRES": "billing=4,cpu=4,gres/gpu=1,mem=16G,node=1",
        "AllocTRES": "(null)",
        "JobState": "PENDING",
        "Priority": "0",
        "EligibleTime": "Unknown",
        "Reason": "JobHeldUser",
    }


def terminal_accounting_record(job_id: str = "12345", token: str = "a" * 24) -> dict[str, str]:
    tres = "billing=4,cpu=4,gres/gpu=1,mem=16G,node=1"
    return {
        "JobIDRaw": job_id,
        "JobName": controller.JOB_NAME,
        "User": controller.OWNER,
        "Account": controller.ACCOUNT,
        "QOS": controller.QOS,
        "Partition": controller.PARTITION,
        "State": "COMPLETED",
        "ExitCode": "0:0",
        "Elapsed": "00:00:02",
        "ReqTRES": tres,
        "AllocTRES": tres,
        "NNodes": "1",
        "ReqCPUS": "4",
        "TimeLimit": controller.WALLTIME,
        "Comment": f"{controller.COMMENT_PREFIX}{token}",
    }


def accounting_line(record: dict[str, str]) -> bytes:
    names = (
        "JobIDRaw",
        "JobName",
        "User",
        "Account",
        "QOS",
        "Partition",
        "State",
        "ExitCode",
        "Elapsed",
        "ReqTRES",
        "AllocTRES",
        "NNodes",
        "ReqCPUS",
        "TimeLimit",
        "Comment",
    )
    return ("|".join(record[name] for name in names) + "|\n").encode()


def test_canonical_has_one_newline() -> None:
    assert controller.canonical({"b": 1, "a": 2}) == b'{"a":2,"b":1}\n'


def test_approval_is_diagnostic_only() -> None:
    contract = controller.approval_contract({"controller": "a" * 64}, {"same_inode": True})
    assert contract["diagnostic_only"] is True
    assert contract["production_authorized"] is False
    assert contract["protocol"]["task_free"] is True
    assert contract["protocol"]["model_free"] is True
    assert contract["protocol"]["one_sbatch"] is True
    assert contract["protocol"]["sealed_memfd_batch_stdin"] is True
    assert contract["protocol"]["spooled_batch_self_hash"] is True
    assert contract["protocol"]["fd_bound_runtime_sources"] is True
    assert contract["protocol"]["dirfd_anchored_cleanup"] is True
    assert contract["protocol"]["retained_scrubbed_roots"] is True
    assert contract["protocol"]["retained_raw_stream_fds"] is True
    assert contract["protocol"]["podman_directory_inode_binding"] is True
    assert contract["protocol"]["per_attempt_podman_directory_binding"] is True
    assert contract["protocol"]["unsafe_entry_preflight"] is True
    assert contract["protocol"]["mountpoint_rejection"] is True
    assert contract["protocol"]["global_cleanup_preflight"] is True
    assert contract["protocol"]["cleanup_single_writer_required"] is True
    assert contract["protocol"]["podman_guard_signal_bound_seconds"] == 3
    assert contract["protocol"]["bounded_signal_cleanup_seconds"] == 210
    assert contract["protocol"]["malformed_submit_output_reconciled"] is True
    assert contract["protocol"]["discovered_id_bound_before_identity_wait"] is True
    assert contract["protocol"]["unknown_id_cleanup_reconciled"] is True
    assert contract["protocol"]["batch_stdin_without_path_operand"] is True
    assert contract["protocol"]["bounded_submit_process_group"] is True
    assert contract["protocol"]["private_bounded_submit_capture"] is True
    assert contract["protocol"]["distinct_submit_outcomes"] is True
    assert contract["protocol"]["submit_timeout_seconds"] == 30
    assert contract["protocol"]["submit_term_grace_seconds"] == 2
    assert contract["protocol"]["submit_kill_grace_seconds"] == 5
    assert contract["protocol"]["submit_output_limit_bytes_per_stream"] == 4096
    assert contract["protocol"]["transient_accounting_retried"] is True
    assert contract["protocol"]["identical_accounting_rows_deduplicated"] is True
    assert contract["protocol"]["stable_terminal_accounting_reads"] == 2
    assert contract["protocol"]["compute_tool_manifest_probe"] == {
        "node": controller.PINNED_NODE,
        "records": 32,
        "vector_sha256": controller.COMPUTE_TOOL_VECTOR_SHA256,
    }
    assert contract["scheduler"]["time"] == "00:30:00"
    assert contract["scheduler"]["nodelist"] == controller.PINNED_NODE


def test_exact_source_and_image_are_bound() -> None:
    contract = controller.approval_contract({}, {})
    assert contract["source_revision"] == "b1f0aa6c1aabcad9182d85a694faaa2eaa3d0f6e"
    assert contract["source_tree"] == "b205ec0f4e2f03f3b3cf5c9e7df7035a49df6772"
    assert contract["image"].endswith("@" + controller.IMAGE_DIGEST)
    assert (
        contract["source_files"]["vllm_tools/serve_api_v2/src/serve_api_v2/worker/worker_vllm.sh"]
        == "c9ad183430e9c50896a0eebc8817a796deed77c5cc51f4cd4208b0e6409b0e87"
    )


def test_parse_tres_accepts_only_exact_map() -> None:
    raw = "node=1,mem=16G,gres/gpu=1,cpu=4,billing=4"
    assert controller.parse_tres(raw, allow_null=False) == controller.EXPECTED_REQ_TRES


@pytest.mark.parametrize(
    "raw",
    [
        "billing=4,cpu=4,mem=16G,node=1",
        "billing=4,cpu=4,gres/gpu=1,mem=16G,node=1,foo=1",
        "billing=4,cpu=8,gres/gpu=1,mem=16G,node=1",
        "billing=4,cpu=4,gres/gpu=1,mem=16G,node=1,node=1",
        "billing=4,cpu=4,gres/gpu=1,mem=16G,node =1",
    ],
)
def test_parse_tres_rejects_drift(raw: str) -> None:
    with pytest.raises(controller.GateError, match="request_tres"):
        controller.parse_tres(raw, allow_null=False)


@pytest.mark.parametrize("raw", [None, "", "None", "(null)", "Unknown"])
def test_parse_tres_null_is_only_explicitly_transient(raw: str | None) -> None:
    assert controller.parse_tres(raw, allow_null=True) is None
    with pytest.raises(controller.GateError, match="request_tres"):
        controller.parse_tres(raw, allow_null=False)


@pytest.mark.parametrize("raw", [None, "", "None", "(null)", "Unknown", "0", "0-1"])
def test_held_node_only_incomplete_is_transient(raw: str | None) -> None:
    record = held_record()
    record["NumNodes"] = raw  # type: ignore[assignment]
    with pytest.raises(controller.IdentityTransient, match="held_nodes"):
        controller.held_identity(record, "12345", "a" * 24)


@pytest.mark.parametrize("raw", [None, "", "None", "(null)", "Unknown", "0", "0-4", "8"])
def test_cpu_projection_never_retries(raw: str | None) -> None:
    record = held_record()
    record["NumCPUs"] = raw  # type: ignore[assignment]
    with pytest.raises(controller.GateError, match="identity_cpus"):
        controller.held_identity(record, "12345", "a" * 24)


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("JobState", "RUNNING", "held_envelope"),
        ("Priority", "1", "held_envelope"),
        ("EligibleTime", "2026-09-20T00:00:00", "held_envelope"),
        ("Reason", "Resources", "held_reason"),
        ("AllocTRES", "billing=4,cpu=4,gres/gpu=1,mem=16G,node=1", "held_alloc_tres"),
        ("ReqNodeList", "g3-154-202", "identity_reqnodelist"),
    ],
)
def test_held_envelope_drift_fails_immediately(field: str, value: str, code: str) -> None:
    record = held_record()
    record[field] = value
    with pytest.raises(controller.GateError, match=code):
        controller.held_identity(record, "12345", "a" * 24)


def test_released_pending_requires_positive_projections() -> None:
    record = held_record()
    record.update(Priority="12", EligibleTime="2026-09-20T06:00:00", Reason="Resources")
    assert controller.released_identity(record, "12345", "a" * 24)


def test_released_node_count_is_strict() -> None:
    record = held_record()
    record.update(Priority="12", EligibleTime="2026-09-20T06:00:00", Reason="Resources", NumNodes="0-1")
    with pytest.raises(controller.GateError, match="released_resources"):
        controller.released_identity(record, "12345", "a" * 24)


def test_released_running_requires_exact_alloc_tres() -> None:
    record = held_record()
    record.update(JobState="RUNNING", Priority="12", EligibleTime="2026-09-20T06:00:00", Reason="None")
    with pytest.raises(controller.IdentityTransient, match="released_alloc_tres"):
        controller.released_identity(record, "12345", "a" * 24)
    record["AllocTRES"] = record["ReqTRES"]
    assert controller.released_identity(record, "12345", "a" * 24)


def test_stable_projection_omits_volatile_scheduler_fields() -> None:
    first = held_record()
    second = dict(first)
    first.update(RunTime="00:00:01", LastSchedEval="2026-09-20T07:00:01")
    second.update(RunTime="00:00:02", LastSchedEval="2026-09-20T07:00:02")
    assert controller.identity_projection(first) == controller.identity_projection(second)


def test_sbatch_command_is_exact_and_held() -> None:
    command = controller.sbatch_command(Path("/private/environment.bin"), "b" * 24)
    assert command.count("/usr/bin/sbatch") == 1
    assert command.count("--hold") == 1
    assert command.count("--nodes=1") == 1
    assert command.count("--ntasks=1") == 1
    assert command.count("--gpus-per-node=1") == 1
    assert command.count(f"--nodelist={controller.PINNED_NODE}") == 1
    assert command.count("--cpus-per-task=4") == 1
    assert command.count("--mem=16G") == 1
    assert command.count("--time=00:30:00") == 1
    assert command.count("--no-requeue") == 1
    assert command.count("--signal=B:TERM@240") == 1
    assert [part for part in command if part.startswith("--export")] == ["--export-file=/private/environment.bin"]
    assert str(controller.BUNDLE / "run_registry_gate.sbatch") not in command
    assert command[-1] == "--export-file=/private/environment.bin"
    assert "-" not in command


def test_environment_is_sorted_nul_and_private(tmp_path: Path) -> None:
    path = tmp_path / "environment.bin"
    observed = controller.write_environment(path, {"B": "2", "A": "1"})
    assert path.read_bytes() == b"A=1\0B=2\0"
    assert observed == controller.digest(path.read_bytes())
    assert stat.S_IMODE(path.stat().st_mode) == 0o400
    with pytest.raises(FileExistsError):
        controller.write_environment(path, {"A": "1"})


def test_environment_rejects_nul_or_equals(tmp_path: Path) -> None:
    with pytest.raises(controller.GateError, match="environment_invalid"):
        controller.write_environment(tmp_path / "one", {"A=B": "x"})
    with pytest.raises(controller.GateError, match="environment_invalid"):
        controller.write_environment(tmp_path / "two", {"A": "x\0y"})


def test_publish_is_no_replace_and_leaves_one_link(tmp_path: Path) -> None:
    target = tmp_path / "output"
    target.mkdir(mode=0o700)
    expected = {"kind": "test", "state": "complete"}
    sha = controller.publish_exclusive(target, "result.json", expected)
    result = target / "result.json"
    assert result.read_bytes() == controller.canonical(expected)
    assert sha == controller.digest(result.read_bytes())
    assert result.stat().st_nlink == 1
    assert not list(target.glob(".*.tmp"))
    with pytest.raises(FileExistsError):
        controller.publish_exclusive(target, "result.json", expected)


def test_publish_cleans_owned_temp_when_link_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "output"
    target.mkdir(mode=0o700)

    def fail_link(*_args: object, **_kwargs: object) -> None:
        raise OSError("injected")

    monkeypatch.setattr(controller.os, "link", fail_link)
    with pytest.raises(OSError, match="injected"):
        controller.publish_exclusive(target, "result.json", {"state": "blocked"})
    assert list(target.iterdir()) == []


def test_terminal_lock_is_retained_and_single_use(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lock_path = tmp_path / "gate.lock"
    monkeypatch.setattr(controller, "LOCK", lock_path)
    lock = controller.acquire_lock()
    controller.finalize_lock(lock, "success")
    assert json.loads(lock_path.read_bytes())["state"] == "terminal"
    assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        controller.acquire_lock()


def test_cleanup_envelope_accepts_only_known_propagation_gaps() -> None:
    record = held_record()
    for field in ("Command", "WorkDir", "Account", "QOS", "Partition", "TimeLimit", "ReqTRES", "NumCPUs"):
        record[field] = "(null)"
    record["NumNodes"] = "0-1"
    assert controller.cancellation_envelope(record, "12345", "a" * 24)


def test_cleanup_envelope_rejects_owner_or_resource_drift() -> None:
    record = held_record()
    record["UserId"] = "other(1)"
    with pytest.raises(controller.GateError, match="cleanup_identity_conflict"):
        controller.cancellation_envelope(record, "12345", "a" * 24)
    record = held_record()
    record["NumCPUs"] = "8"
    with pytest.raises(controller.GateError, match="cleanup_identity_conflict"):
        controller.cancellation_envelope(record, "12345", "a" * 24)


def test_submit_retries_transient_name_query_without_resubmit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = "12345"
    calls = {"submit": 0, "query": 0, "stable": 0}
    batch_raw = b"#!/usr/bin/bash\nexit 0\n"
    submitted: dict[str, object] = {}

    def fake_submit(_argv: object, stdin_fd: int) -> controller.SubmitAttempt:
        calls["submit"] += 1
        submitted["raw"] = os.read(stdin_fd, len(batch_raw) + 1)
        submitted["seals"] = fcntl.fcntl(stdin_fd, fcntl.F_GET_SEALS)
        return controller.SubmitAttempt("completed", 0, f"{job_id}\n".encode(), b"", True)

    def fake_query() -> set[str]:
        calls["query"] += 1
        if calls["query"] == 1:
            raise controller.SchedulerUnavailable("squeue_failed")
        return {job_id} if calls["query"] == 2 else set()

    def fake_stable(*_args: object, **_kwargs: object) -> dict[str, str]:
        calls["stable"] += 1
        return held_record()

    monkeypatch.setattr(controller, "SUBMITTED_JOB_ID", None)
    monkeypatch.setattr(controller, "OWNED_JOB_IDS", set())
    monkeypatch.setattr(controller, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(controller, "bounded_submit", fake_submit)
    monkeypatch.setattr(controller, "queue_name_ids", fake_query)
    monkeypatch.setattr(controller, "stable_reads", fake_stable)
    monkeypatch.setattr(controller.time, "sleep", lambda _seconds: None)
    assert controller.submit_once(Path("/private/environment"), "a" * 24, batch_raw) == job_id
    assert calls == {"submit": 1, "query": 3, "stable": 1}
    assert submitted["raw"] == batch_raw
    assert submitted["seals"] == (fcntl.F_SEAL_SEAL | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_GROW | fcntl.F_SEAL_WRITE)
    assert job_id in controller.OWNED_JOB_IDS


def test_direct_id_is_retained_before_submission_conflict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = "12345"
    monkeypatch.setattr(controller, "SUBMITTED_JOB_ID", None)
    monkeypatch.setattr(controller, "OWNED_JOB_IDS", set())
    monkeypatch.setattr(controller, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(
        controller,
        "bounded_submit",
        lambda *_args, **_kwargs: controller.SubmitAttempt("completed", 0, f"{job_id}\n".encode(), b"", True),
    )
    monkeypatch.setattr(controller, "queue_name_ids", lambda: {job_id, "12346"})
    with pytest.raises(controller.GateError, match="submission_conflict"):
        controller.submit_once(Path("/private/environment"), "a" * 24, b"#!/usr/bin/bash\nexit 0\n")
    assert controller.SUBMITTED_JOB_ID == job_id
    assert job_id in controller.OWNED_JOB_IDS


@pytest.mark.parametrize(
    "error",
    [controller.GateInterrupted(), controller.SchedulerUnavailable("show_job_unavailable")],
)
def test_discovered_id_is_bound_before_identity_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    job_id = "12345"
    batch_raw = b"#!/usr/bin/bash\nexit 0\n"
    monkeypatch.setattr(controller, "SUBMITTED_JOB_ID", None)
    monkeypatch.setattr(controller, "OWNED_JOB_IDS", set())
    monkeypatch.setattr(controller, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(
        controller,
        "bounded_submit",
        lambda *_args, **_kwargs: controller.SubmitAttempt("completed", 0, b"not-a-job-id\n", b"", True),
    )
    monkeypatch.setattr(controller, "queue_name_ids", lambda: {job_id})

    def fail_stable(*_args: object, **_kwargs: object) -> dict[str, str]:
        assert controller.SUBMITTED_JOB_ID == job_id
        assert job_id in controller.OWNED_JOB_IDS
        raise error

    monkeypatch.setattr(controller, "stable_reads", fail_stable)
    with pytest.raises(type(error)):
        controller.submit_once(Path("/private/environment"), "a" * 24, batch_raw)
    assert controller.SUBMITTED_JOB_ID == job_id
    assert job_id in controller.OWNED_JOB_IDS


def test_malformed_sbatch_stdout_enters_bounded_name_reconciliation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = "12345"
    calls = {"submit": 0, "query": 0, "stable": 0}

    def fake_submit(*_args: object, **_kwargs: object) -> controller.SubmitAttempt:
        calls["submit"] += 1
        return controller.SubmitAttempt("completed", 0, b"\xff\xfe\n", b"", True)

    def fake_query() -> set[str]:
        calls["query"] += 1
        if calls["query"] == 1:
            raise controller.SchedulerUnavailable("squeue_unavailable")
        return {job_id} if calls["query"] == 2 else set()

    def fake_stable(*_args: object, **_kwargs: object) -> dict[str, str]:
        calls["stable"] += 1
        assert controller.SUBMITTED_JOB_ID == job_id
        assert job_id in controller.OWNED_JOB_IDS
        return held_record()

    monkeypatch.setattr(controller, "SUBMITTED_JOB_ID", None)
    monkeypatch.setattr(controller, "OWNED_JOB_IDS", set())
    monkeypatch.setattr(controller, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(controller, "bounded_submit", fake_submit)
    monkeypatch.setattr(controller, "queue_name_ids", fake_query)
    monkeypatch.setattr(controller, "stable_reads", fake_stable)
    monkeypatch.setattr(controller.time, "sleep", lambda _seconds: None)
    assert controller.submit_once(Path("/private/environment"), "a" * 24, b"#!/usr/bin/bash\n") == job_id
    assert calls == {"submit": 1, "query": 3, "stable": 1}


def test_submit_nonzero_is_distinct_and_raw_capture_stays_private(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stderr = b"private scheduler diagnostic"
    clock = [0.0]
    monkeypatch.setattr(controller, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(controller, "SUBMITTED_JOB_ID", None)
    monkeypatch.setattr(controller, "OWNED_JOB_IDS", set())
    monkeypatch.setattr(
        controller,
        "bounded_submit",
        lambda *_args, **_kwargs: controller.SubmitAttempt("completed", 1, b"", stderr, True),
    )
    monkeypatch.setattr(controller, "queue_name_ids", lambda: set())
    monkeypatch.setattr(controller.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(controller.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    with pytest.raises(controller.GateError, match="submit_nonzero"):
        controller.submit_once(Path("/private/environment"), "a" * 24, b"#!/usr/bin/bash\n")
    assert (tmp_path / "sbatch.stdout.raw").read_bytes() == b""
    assert (tmp_path / "sbatch.stderr.raw").read_bytes() == stderr
    receipt_raw = (tmp_path / "submit_attempt.json").read_bytes()
    receipt = json.loads(receipt_raw)
    assert stderr not in receipt_raw
    assert receipt["primary_outcome"] == "completed"
    assert receipt["returncode"] == 1
    assert receipt["stderr_captured_size"] == len(stderr)
    assert receipt["stderr_observed_size"] == len(stderr)
    assert receipt["stderr_truncated"] is False
    assert receipt["parse_result"] == "absent"
    assert receipt["parsed_job_id"] is None
    assert receipt["stderr_sha256"] == hashlib.sha256(stderr).hexdigest()
    for name in ("sbatch.stdout.raw", "sbatch.stderr.raw", "submit_attempt.json"):
        assert stat.S_IMODE((tmp_path / name).stat().st_mode) == 0o400


def test_bounded_submit_times_out_and_reaps_process_group(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(controller, "SUBMIT_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(controller, "SUBMIT_TERM_GRACE_SECONDS", 0.2)
    monkeypatch.setattr(controller, "SUBMIT_KILL_GRACE_SECONDS", 0.5)
    fd = os.memfd_create("registry-gate-test-stdin", os.MFD_CLOEXEC)
    try:
        attempt = controller.bounded_submit(
            ["/usr/bin/bash", "-c", "printf partial; printf diagnostic >&2; sleep 30 & wait"], fd
        )
    finally:
        os.close(fd)
    assert attempt.outcome == "timeout"
    assert attempt.group_terminal is True
    assert attempt.stdout == b"partial"
    assert attempt.stderr == b"diagnostic"


def test_bounded_submit_caps_each_stream_and_kills_group(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(controller, "SUBMIT_OUTPUT_LIMIT", 128)
    fd = os.memfd_create("registry-gate-test-stdin", os.MFD_CLOEXEC)
    try:
        attempt = controller.bounded_submit(
            ["/usr/bin/python3.12", "-c", "import os,time;os.write(1,b'x'*4096);time.sleep(30)"], fd
        )
    finally:
        os.close(fd)
    assert attempt.outcome == "output_oversize"
    assert attempt.group_terminal is True
    assert attempt.stdout == b"x" * 128
    assert attempt.stderr == b""


def test_bounded_submit_accepts_exact_limit_on_both_streams(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(controller, "SUBMIT_OUTPUT_LIMIT", 128)
    fd = os.memfd_create("registry-gate-test-stdin", os.MFD_CLOEXEC)
    try:
        attempt = controller.bounded_submit(
            [
                "/usr/bin/python3.12",
                "-c",
                "import os;os.write(1,b'x'*128);os.write(2,b'y'*128)",
            ],
            fd,
        )
    finally:
        os.close(fd)
    assert attempt.outcome == "completed"
    assert attempt.returncode == 0
    assert attempt.group_terminal is True
    assert attempt.stdout == b"x" * 128
    assert attempt.stderr == b"y" * 128
    assert attempt.stdout_observed_size == attempt.stderr_observed_size == 128


def test_bounded_submit_caps_both_streams(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(controller, "SUBMIT_OUTPUT_LIMIT", 128)
    fd = os.memfd_create("registry-gate-test-stdin", os.MFD_CLOEXEC)
    try:
        attempt = controller.bounded_submit(
            [
                "/usr/bin/python3.12",
                "-c",
                "import os,time;os.write(1,b'x'*4096);os.write(2,b'y'*4096);time.sleep(30)",
            ],
            fd,
        )
    finally:
        os.close(fd)
    assert attempt.outcome == "output_oversize"
    assert attempt.group_terminal is True
    assert attempt.stdout == b"x" * 128
    assert attempt.stderr == b"y" * 128
    assert attempt.stdout_observed_size >= 4096
    assert attempt.stderr_observed_size >= 4096


def test_bounded_submit_escalates_term_ignoring_group(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(controller, "SUBMIT_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(controller, "SUBMIT_TERM_GRACE_SECONDS", 0.2)
    monkeypatch.setattr(controller, "SUBMIT_KILL_GRACE_SECONDS", 0.5)
    fd = os.memfd_create("registry-gate-test-stdin", os.MFD_CLOEXEC)
    try:
        attempt = controller.bounded_submit(
            [
                "/usr/bin/python3.12",
                "-c",
                "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)",
            ],
            fd,
        )
    finally:
        os.close(fd)
    assert attempt.outcome == "timeout"
    assert attempt.group_terminal is True
    assert attempt.returncode == -signal.SIGKILL


def test_bounded_submit_signal_preserves_primary_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(controller, "INTERRUPTED", False)
    monkeypatch.setattr(controller, "SUBMIT_TIMEOUT_SECONDS", 5)
    monkeypatch.setattr(controller, "SUBMIT_TERM_GRACE_SECONDS", 0.2)
    monkeypatch.setattr(controller, "SUBMIT_KILL_GRACE_SECONDS", 0.5)
    timer = threading.Timer(0.1, lambda: setattr(controller, "INTERRUPTED", True))
    fd = os.memfd_create("registry-gate-test-stdin", os.MFD_CLOEXEC)
    timer.start()
    try:
        attempt = controller.bounded_submit(["/usr/bin/python3.12", "-c", "import time;time.sleep(30)"], fd)
    finally:
        timer.cancel()
        controller.INTERRUPTED = False
        os.close(fd)
    assert attempt.outcome == "signal"
    assert attempt.group_terminal is True


def test_bounded_submit_distinguishes_exec_error() -> None:
    fd = os.memfd_create("registry-gate-test-stdin", os.MFD_CLOEXEC)
    try:
        attempt = controller.bounded_submit(["/definitely/not/a/program"], fd)
    finally:
        os.close(fd)
    assert attempt.outcome == "exec_error"
    assert attempt.returncode is None
    assert attempt.stdout == attempt.stderr == b""
    assert attempt.group_terminal is True
    assert attempt.stdout_observed_size == attempt.stderr_observed_size == 0


def test_submit_capture_hidden_temp_is_removed_on_publish_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(controller, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(controller.os, "link", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("injected")))
    with pytest.raises(OSError, match="injected"):
        controller.record_submit_attempt(
            controller.SubmitAttempt("completed", 1, b"private-out", b"private-err", True), "absent", None
        )
    assert list(tmp_path.iterdir()) == []


def test_cancel_exact_accepts_partial_propagation_then_proves_absence(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = "12345"
    token = "a" * 24
    partial = held_record()
    partial.update(Command="(null)", WorkDir="(null)", ReqTRES="(null)", NumNodes="0-1")
    queue_reads = iter(({job_id}, set(), set()))
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(controller, "OWNED_JOB_IDS", {job_id})
    monkeypatch.setattr(controller, "show_job", lambda _job_id: partial)
    monkeypatch.setattr(controller, "queue_name_ids", lambda: next(queue_reads))
    monkeypatch.setattr(controller.time, "sleep", lambda _seconds: None)

    def fake_run(argv: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        commands.append(argv)
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(controller, "run", fake_run)
    controller.cancel_exact(job_id, token)
    assert commands == [("/usr/bin/scancel", "-M", controller.CLUSTER, job_id)]


def test_cancel_never_targets_unproven_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = "12345"
    token = "a" * 24
    partial = held_record()
    partial["Comment"] = "(null)"
    clock = [0.0]
    monkeypatch.setattr(controller, "OWNED_JOB_IDS", {job_id})
    monkeypatch.setattr(controller, "show_job", lambda _job_id: partial)
    monkeypatch.setattr(controller, "queue_name_ids", lambda: set())
    monkeypatch.setattr(controller.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(controller.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(
        controller,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not cancel unproven identity")),
    )
    controller.cancel_exact(job_id, token)


def test_cleanup_reconciles_unknown_id_after_submit_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = "12345"
    token = "a" * 24
    queue_reads: list[set[str] | BaseException] = [
        controller.SchedulerUnavailable("squeue_unavailable"),
        {job_id},
        set(),
        set(),
    ]
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(controller, "SUBMISSION_ATTEMPTED", True)
    monkeypatch.setattr(controller, "SUBMITTED_JOB_ID", None)
    monkeypatch.setattr(controller, "OWNED_JOB_IDS", set())

    def fake_query() -> set[str]:
        observed = queue_reads.pop(0)
        if isinstance(observed, BaseException):
            raise observed
        return observed

    def fake_run(argv: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        commands.append(argv)
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(controller, "queue_name_ids", fake_query)
    monkeypatch.setattr(controller, "show_job", lambda _job_id: held_record())
    monkeypatch.setattr(controller, "run", fake_run)
    monkeypatch.setattr(controller.time, "sleep", lambda _seconds: None)
    controller.cancel_exact(None, token)
    assert controller.SUBMITTED_JOB_ID == job_id
    assert job_id in controller.OWNED_JOB_IDS
    assert commands == [("/usr/bin/scancel", "-M", controller.CLUSTER, job_id)]


def test_cleanup_without_submit_attempt_does_not_query(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(controller, "SUBMISSION_ATTEMPTED", False)
    monkeypatch.setattr(
        controller,
        "queue_name_ids",
        lambda: (_ for _ in ()).throw(AssertionError("must not query without a submit attempt")),
    )
    controller.cancel_exact(None, "a" * 24)


def test_accounting_treats_malformed_propagation_as_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        controller,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, b"partial-row\n", b""),
    )
    with pytest.raises(controller.IdentityTransient, match="accounting_shape"):
        controller.accounting("12345")


def test_accounting_deduplicates_identical_exact_rows_and_ignores_steps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = terminal_accounting_record()
    step = dict(record, JobIDRaw="12345.batch", JobName="batch")
    raw = accounting_line(record) + accounting_line(record) + accounting_line(step)
    monkeypatch.setattr(
        controller,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, raw, b""),
    )
    assert controller.accounting("12345") == record


def test_accounting_with_only_requested_job_steps_is_not_yet_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    record = terminal_accounting_record()
    raw = accounting_line(dict(record, JobIDRaw="12345.batch", JobName="batch"))
    monkeypatch.setattr(
        controller,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, raw, b""),
    )
    assert controller.accounting("12345") is None


def test_accounting_retries_conflicting_duplicate_exact_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    first = terminal_accounting_record()
    second = dict(first, State="FAILED", ExitCode="2:0")
    raw = accounting_line(first) + accounting_line(second)
    monkeypatch.setattr(
        controller,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, raw, b""),
    )
    with pytest.raises(controller.IdentityTransient, match="accounting_duplicate"):
        controller.accounting("12345")


def test_accounting_rejects_unrelated_job_row(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = accounting_line(dict(terminal_accounting_record(), JobIDRaw="99999"))
    monkeypatch.setattr(
        controller,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, raw, b""),
    )
    with pytest.raises(controller.GateError, match="accounting_unexpected_job"):
        controller.accounting("12345")


@pytest.mark.parametrize("row_id", ["99999.batch", "99999.extern", "99999.0"])
def test_accounting_rejects_unrelated_step_row(row_id: str, monkeypatch: pytest.MonkeyPatch) -> None:
    raw = accounting_line(dict(terminal_accounting_record(), JobIDRaw=row_id))
    monkeypatch.setattr(
        controller,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, raw, b""),
    )
    with pytest.raises(controller.GateError, match="accounting_unexpected_job"):
        controller.accounting("12345")


@pytest.mark.parametrize("row_id", ["", "None", "(null)", "Unknown", "not-a-job"])
def test_accounting_retries_incomplete_or_malformed_job_id(row_id: str, monkeypatch: pytest.MonkeyPatch) -> None:
    raw = accounting_line(dict(terminal_accounting_record(), JobIDRaw=row_id))
    monkeypatch.setattr(
        controller,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, raw, b""),
    )
    with pytest.raises(controller.IdentityTransient, match="accounting_job_id"):
        controller.accounting("12345")


def test_wait_terminal_retries_transient_and_incomplete_rows_until_two_stable_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending = dict(terminal_accounting_record(), State="COMPLETING")
    stage_out = dict(terminal_accounting_record(), State="STAGE_OUT")
    malformed_state = dict(terminal_accounting_record(), State="???")
    incomplete = dict(terminal_accounting_record(), AllocTRES="")
    incomplete_exit = dict(terminal_accounting_record(), ExitCode="")
    incomplete_elapsed = dict(terminal_accounting_record(), Elapsed="")
    malformed_exit = dict(terminal_accounting_record(), ExitCode="zero")
    malformed_elapsed = dict(terminal_accounting_record(), Elapsed="two-seconds")
    terminal = terminal_accounting_record()
    observations: list[dict[str, str] | None | BaseException] = [
        controller.SchedulerUnavailable("accounting_unavailable"),
        controller.IdentityTransient("accounting_shape"),
        None,
        pending,
        stage_out,
        malformed_state,
        incomplete,
        incomplete_exit,
        incomplete_elapsed,
        malformed_exit,
        malformed_elapsed,
        terminal,
        dict(terminal),
    ]

    def fake_accounting(_job_id: str) -> dict[str, str] | None:
        observed = observations.pop(0)
        if isinstance(observed, BaseException):
            raise observed
        return observed

    monkeypatch.setattr(controller, "accounting", fake_accounting)
    monkeypatch.setattr(controller.time, "sleep", lambda _seconds: None)
    assert controller.wait_terminal("12345", "a" * 24) == terminal
    assert observations == []


def test_wait_terminal_resets_stability_after_transient_observation(monkeypatch: pytest.MonkeyPatch) -> None:
    terminal = terminal_accounting_record()
    observations: list[dict[str, str] | BaseException] = [
        terminal,
        controller.IdentityTransient("accounting_duplicate"),
        dict(terminal),
        dict(terminal),
    ]

    def fake_accounting(_job_id: str) -> dict[str, str]:
        observed = observations.pop(0)
        if isinstance(observed, BaseException):
            raise observed
        return observed

    monkeypatch.setattr(controller, "accounting", fake_accounting)
    monkeypatch.setattr(controller.time, "sleep", lambda _seconds: None)
    assert controller.wait_terminal("12345", "a" * 24) == terminal
    assert observations == []


def test_terminal_accounting_rejects_nonnull_identity_drift() -> None:
    record = dict(terminal_accounting_record(), Account="different")
    with pytest.raises(controller.GateError, match="accounting_identity"):
        controller.validate_terminal_accounting(record, "12345", "a" * 24)


def test_nonterminal_accounting_rejects_nonnull_identity_drift() -> None:
    record = dict(terminal_accounting_record(), State="COMPLETING", Account="different")
    with pytest.raises(controller.GateError, match="accounting_identity"):
        controller.validate_accounting_identity(record, "12345", "a" * 24)


@pytest.mark.parametrize("state", ["STAGE_OUT", "SIGNALING", "SUSPENDED"])
def test_nonterminal_accounting_state_is_retryable(state: str) -> None:
    record = dict(terminal_accounting_record(), State=state)
    controller.validate_accounting_identity(record, "12345", "a" * 24)


@pytest.mark.parametrize("state", ["", "   ", "???"])
def test_missing_or_malformed_accounting_state_is_transient(state: str) -> None:
    record = dict(terminal_accounting_record(), State=state)
    with pytest.raises(controller.IdentityTransient, match="accounting_state_(?:incomplete|malformed)"):
        controller.validate_accounting_identity(record, "12345", "a" * 24)


@pytest.mark.parametrize("field", ["ExitCode", "Elapsed"])
def test_terminal_accounting_treats_missing_outcome_as_transient(field: str) -> None:
    record = dict(terminal_accounting_record(), **{field: ""})
    with pytest.raises(controller.IdentityTransient, match="accounting_outcome_incomplete"):
        controller.validate_terminal_accounting(record, "12345", "a" * 24)


@pytest.mark.parametrize(("field", "value"), [("ExitCode", "zero"), ("Elapsed", "two-seconds")])
def test_terminal_accounting_retries_malformed_outcome(field: str, value: str) -> None:
    record = dict(terminal_accounting_record(), **{field: value})
    with pytest.raises(controller.IdentityTransient, match="accounting_outcome_malformed"):
        controller.validate_terminal_accounting(record, "12345", "a" * 24)


def test_tmux_ancestry_parser_handles_parenthesized_command(tmp_path: Path) -> None:
    for pid, parent in ((300, 200), (200, 100), (100, 1)):
        directory = tmp_path / str(pid)
        directory.mkdir()
        (directory / "stat").write_text(f"{pid} (name with ) paren) S {parent} 0 0 0\n")
    assert controller.pid_ancestry_contains(300, 100, tmp_path)
    assert not controller.pid_ancestry_contains(300, 99, tmp_path)


def test_tmux_validation_accepts_python_foreground_via_ancestry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TMUX_PANE", "%0")
    monkeypatch.setattr(
        controller,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, b"swebench_vmvm:Launcher.0|42\n", b""),
    )
    monkeypatch.setattr(controller, "pid_ancestry_contains", lambda start, target: start > 1 and target == 42)
    controller.validate_tmux()


def test_tmux_validation_rejects_unrelated_pane(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TMUX_PANE", "%0")
    monkeypatch.setattr(
        controller,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, b"swebench_vmvm:Launcher.0|42\n", b""),
    )
    monkeypatch.setattr(controller, "pid_ancestry_contains", lambda _start, _target: False)
    with pytest.raises(controller.GateError, match="tmux_identity"):
        controller.validate_tmux()


def test_error_code_is_sanitized() -> None:
    assert controller.error_code(controller.GateError("safe_code")) == "safe_code"
    assert controller.error_code(controller.GateError("raw / path")) == "internal_error"
    assert controller.error_code(ValueError("secret")) == "internal_error"


def test_probe_calls_only_registry_preparation_functions() -> None:
    text = (HERE / "probe_registry_gate.sh").read_text()
    for call in (
        "_container_registry_arm_cleanup",
        '_container_registry_login "$GATE_IMAGE"',
        '_container_registry_pull "$GATE_IMAGE"',
        "_container_registry_disarm_cleanup",
    ):
        assert text.count(call) == 1
    assert "container_run " not in text
    assert "/usr/bin/podman run" not in text
    assert "nvidia-container" not in text
    assert "vllm serve" not in text


def test_probe_descriptor_only_execs_restore_private_stderr(tmp_path: Path) -> None:
    text = (HERE / "probe_registry_gate.sh").read_text()
    for fragment in (
        '{ exec 9<"$worker" 8<"$aws_creds" 7<"$tools_manifest"',
        '{ exec 4<"$tls_source"; } 2>/dev/null',
        '{ exec {private_root_fd}<"$private_root"; } 2>/dev/null',
        '{ exec {storage_conf_fd}<>"$storage_conf"; } 2>/dev/null',
        '{ exec {local_tls_fd}<>"$local_tls"; } 2>/dev/null',
        '{ exec {inspect_fd}<>"$inspect_file"; } 2>/dev/null',
        '{ exec {graphroot_fd}<"$graphroot" {runroot_fd}<"$runroot"',
        '{ exec {auth_fd}<>"$auth_path"; } 2>/dev/null',
    ):
        assert fragment in text
    assert not re.search(r"(?m)^\s*(?:if ! )?exec .*2>/dev/null", text)
    descriptor_file = tmp_path / "descriptor"
    descriptor_file.write_bytes(b"bound")
    shell = (
        "before=$(/usr/bin/stat -Lc '%d:%i' /proc/self/fd/2); "
        '{ exec {data_fd}<>"$1"; } 2>/dev/null; '
        "after=$(/usr/bin/stat -Lc '%d:%i' /proc/self/fd/2); "
        '[[ "$before" == "$after" && -f "/proc/self/fd/$data_fd" ]] || exit 2; '
        '/usr/bin/printf "stderr-restored" >&2'
    )
    result = subprocess.run(
        ["/usr/bin/bash", "-p", "-c", shell, "descriptor-open", str(descriptor_file)],
        check=False,
        capture_output=True,
    )
    assert result.returncode == 0
    assert result.stdout == b""
    assert result.stderr == b"stderr-restored"


def test_batch_has_one_production_shaped_srun() -> None:
    text = (HERE / "run_registry_gate.sbatch").read_text()
    probe = (HERE / "probe_registry_gate.sh").read_text()
    assert text.count("/usr/bin/srun -M") == 1
    for fragment in (
        "--overlap",
        "--nodes=1",
        "--ntasks=1",
        "--gpus-per-node=1",
        "--cpus-per-task=4",
        "--cpu-bind=none",
        "--export=ALL",
    ):
        assert fragment in text
    assert '[[ "$node" == g3-154-201 ]]' in text
    assert '"${SLURMD_NODENAME:-}" == g3-154-201' in probe


def test_batch_public_output_is_only_emit() -> None:
    text = (HERE / "run_registry_gate.sbatch").read_text()
    assert "raw=$(/usr/bin/printf" in text
    assert '/usr/bin/printf \'%s\' "$raw" > "$temp"' in text
    assert "/usr/bin/printf '%s' \"$raw\" | /usr/bin/sha256sum" in text
    assert text.count("\n    /usr/bin/printf '%s' \"$raw\" >&8\n") == 1
    assert "exec 8>&1 4>&2 >/dev/null 2>/dev/null" in text
    assert '>&"$stdout_fd" 2>&"$stderr_fd"' in text
    assert "GATE_JOB_RESULT" in text
    assert '/usr/bin/ln -- "$temp" "$GATE_JOB_RESULT"' in text
    for line in text.splitlines():
        if "/usr/bin/unlink --" in line:
            assert line.count('"$') == 1
        if line.lstrip().startswith("emit "):
            assert "|| exit 3" in line


def test_batch_empty_log_uses_numeric_identity_not_percent_f(tmp_path: Path) -> None:
    empty = tmp_path / "empty.log"
    empty.touch(mode=0o600)
    observed = subprocess.run(
        ["/usr/bin/stat", "-Lc", "%F", str(empty)], check=True, capture_output=True, text=True
    ).stdout.strip()
    assert observed == "regular empty file"
    text = (HERE / "run_registry_gate.sbatch").read_text()
    log_block = text[text.index("stable_log_reads=0") : text.index("readonly local_parent")]
    assert "%F" not in log_block
    assert "/proc/self/fd/8" in log_block and "/proc/self/fd/4" in log_block


def test_exact_bytes_are_executed_from_bound_descriptors() -> None:
    batch = (HERE / "run_registry_gate.sbatch").read_text()
    probe = (HERE / "probe_registry_gate.sh").read_text()
    assert 'exec 9<"${BASH_SOURCE[0]}" 7<"$classifier" 6<"$probe" 5<"$tools_manifest"' in batch
    assert "/usr/bin/sha256sum -- /proc/self/fd/9" in batch
    assert 'exec </proc/self/fd/6 >&"$stdout_fd" 2>&"$stderr_fd"' in batch
    assert 'classify_registry_error_file "$stderr_stream" "$rc" "$stderr_identity"' in batch
    assert "exec /usr/bin/setsid /usr/bin/timeout" in batch
    assert "/usr/bin/bash -p -s" in batch
    assert "source /proc/self/fd/8" in probe
    assert "source /proc/self/fd/9" in probe
    assert 'exec 9<"$worker" 8<"$aws_creds" 7<"$tools_manifest"' in probe
    assert (
        "/usr/bin/sha256sum -c --strict /proc/self/fd/5 >/dev/null 2>&1 \\\n    || block compute_tools_identity"
    ) in batch
    assert "compute_tools_identity" in controller.ALLOWED_PUBLIC_CATEGORIES


def test_cleanup_traps_precede_first_mktemp() -> None:
    batch = (HERE / "run_registry_gate.sbatch").read_text()
    probe = (HERE / "probe_registry_gate.sh").read_text()
    assert "shopt -u varredir_close" in batch
    assert "shopt -u varredir_close" in probe
    assert batch.index("trap early_cleanup EXIT") < batch.index("private=$(/usr/bin/mktemp")
    assert probe.index("trap early_cleanup EXIT") < probe.index("private_root=$(/usr/bin/mktemp")
    assert (
        batch.index("private=$(/usr/bin/mktemp")
        < batch.index('exec {private_fd}<"$private"')
        < batch.index('/usr/bin/touch "$stdout"')
    )
    assert (
        probe.index("private_root=$(/usr/bin/mktemp")
        < probe.index('exec {private_root_fd}<"$private_root"')
        < probe.index('/usr/bin/mkdir -m 700 -- "$graphroot"')
    )


def test_private_cleanup_makes_read_only_files_writable_before_truncation() -> None:
    batch = (HERE / "run_registry_gate.sbatch").read_text()
    probe = (HERE / "probe_registry_gate.sh").read_text()
    scrub = batch[batch.index("scrub_exact_batch_file()") : batch.index("scrub_batch_contents()")]
    assert scrub.index('/usr/bin/chmod 600 -- "/proc/self/fd/$fd"') < scrub.index(
        '/usr/bin/truncate -s 0 -- "/proc/self/fd/$fd"'
    )
    scrub = probe[probe.index("scrub_anchored_directory()") : probe.index("scrub_exact_probe_file()")]
    chmod = scrub.index("-exec /usr/bin/chmod u+rwx")
    truncate = scrub.index("-exec /usr/bin/truncate")
    assert chmod < truncate
    assert "-type f -links 1" in scrub


def _batch_cleanup_functions() -> str:
    text = (HERE / "run_registry_gate.sbatch").read_text()
    return text[text.index("close_batch_private_fds()") : text.index("early_cleanup()")]


def _batch_fd_setup() -> str:
    return (
        "set -euo pipefail\nGATE_EXPECTED_UID=$(id -u)\n"
        "private=$1/original\n"
        'mkdir -m 700 -- "$private"\n'
        "private_fd=-1\nstdout_fd=-1\nstderr_fd=-1\nlocal_tools_fd=-1\n"
        'exec {private_fd}<"$private"\n'
        "private_anchor=/proc/self/fd/${private_fd}/.\n"
        "private_identity=$(stat -Lc '%d:%i:%a:%u' \"$private_anchor\")\n"
        "private_anchor_trusted=1\ncleanup_attempted=0\n"
        "stdout=$private_anchor/stdout\nstderr=$private_anchor/stderr\n"
        "local_tools=$private_anchor/compute_tools.sha256\n"
        'touch "$stdout" "$stderr" "$local_tools"\n'
        'printf tools > "$local_tools"\n'
        'chmod 600 "$stdout" "$stderr"; chmod 400 "$local_tools"\n'
        'exec {stdout_fd}<>"$stdout" {stderr_fd}<>"$stderr" {local_tools_fd}<"$local_tools"\n'
        "stdout_identity=$(stat -Lc '%d:%i:%a:%u:%h' /proc/self/fd/$stdout_fd)\n"
        "stderr_identity=$(stat -Lc '%d:%i:%a:%u:%h' /proc/self/fd/$stderr_fd)\n"
        "local_tools_identity=$(stat -Lc '%d:%i:%a:%u:%h' /proc/self/fd/$local_tools_fd)\n"
        "printf stdout-secret > /proc/self/fd/$stdout_fd\n"
        "printf stderr-secret > /proc/self/fd/$stderr_fd\n"
        "exec {check_stdout}>&$stdout_fd {check_stderr}>&$stderr_fd\n"
    )


def test_batch_retains_scrubbed_root_and_exact_log_descriptors(tmp_path: Path) -> None:
    script = (
        _batch_fd_setup() + _batch_cleanup_functions() + "\nretain_batch_root\n"
        "[[ -d $private && ! -L $private ]]\n"
        "[[ $private_fd == -1 && $stdout_fd == -1 && $stderr_fd == -1 && $local_tools_fd == -1 ]]\n"
        "[[ $(stat -Lc %s /proc/self/fd/$check_stdout) == 0 ]]\n"
        "[[ $(stat -Lc %s /proc/self/fd/$check_stderr) == 0 ]]\n"
        '[[ $(stat -c %s "$private/stdout") == 0 && $(stat -c %s "$private/stderr") == 0 ]]\n'
        '[[ $(stat -c %s "$private/compute_tools.sha256") == 0 ]]\n'
        '[[ -z "$(find "$private" -mindepth 1 ! -name stdout ! -name stderr ! -name compute_tools.sha256 -print -quit)" ]]\n'
        "exec {check_stdout}>&- {check_stderr}>&-\n"
    )
    result = subprocess.run(["/usr/bin/bash", "-p", "-c", script, "anchor-test", str(tmp_path)], capture_output=True)
    assert result.returncode == 0, result.stderr.decode()


def test_batch_empty_root_swap_after_scrub_is_preserved(tmp_path: Path) -> None:
    script = (
        _batch_fd_setup()
        + _batch_cleanup_functions()
        + '\nscrub_batch_contents\nmoved=$1/moved\nmv "$private" "$moved"\nmkdir -m 700 -- "$private"\n'
        'replacement_identity=$(stat -c "%d:%i" "$private")\n'
        "set +e; retain_batch_root; rc=$?; set -e\n"
        "[[ $rc -ne 0 ]]\n"
        '[[ $(stat -c "%d:%i" "$private") == "$replacement_identity" ]]\n'
        '[[ $(stat -c %s "$moved/compute_tools.sha256") == 0 ]]\n'
        "[[ $(stat -Lc %s /proc/self/fd/$check_stdout) == 0 ]]\n"
        "[[ $(stat -Lc %s /proc/self/fd/$check_stderr) == 0 ]]\n"
        "exec {check_stdout}>&- {check_stderr}>&-\n"
    )
    result = subprocess.run(["/usr/bin/bash", "-p", "-c", script, "anchor-test", str(tmp_path)], capture_output=True)
    assert result.returncode == 0, result.stderr.decode()


def test_batch_named_log_replacement_is_preserved_while_exact_inode_is_scrubbed(tmp_path: Path) -> None:
    script = (
        _batch_fd_setup()
        + _batch_cleanup_functions()
        + '\nmv "$private/stdout" "$1/moved-stdout"\nprintf keep > "$private/stdout"\n'
        "set +e; retain_batch_root; rc=$?; set -e\n"
        "[[ $rc -ne 0 ]]\n"
        '[[ $(<"$private/stdout") == keep ]]\n'
        '[[ $(stat -c %s "$1/moved-stdout") == 0 ]]\n'
        "[[ $(stat -Lc %s /proc/self/fd/$check_stdout) == 0 ]]\n"
        "[[ $(stat -Lc %s /proc/self/fd/$check_stderr) == 0 ]]\n"
        "exec {check_stdout}>&- {check_stderr}>&-\n"
    )
    result = subprocess.run(["/usr/bin/bash", "-p", "-c", script, "inode-test", str(tmp_path)], capture_output=True)
    assert result.returncode == 0, result.stderr.decode()


def test_batch_global_preflight_rejects_before_any_log_mutation(tmp_path: Path) -> None:
    script = (
        _batch_fd_setup() + _batch_cleanup_functions() + '\nln "$private/compute_tools.sha256" "$1/outside-hardlink"\n'
        "set +e; scrub_batch_contents; rc=$?; set -e\n"
        "[[ $rc -ne 0 ]]\n"
        '[[ $(<"$private/stdout") == stdout-secret && $(<"$private/stderr") == stderr-secret ]]\n'
        '[[ $(<"$private/compute_tools.sha256") == tools ]]\n'
        "exec {check_stdout}>&- {check_stderr}>&-\n"
    )
    result = subprocess.run(
        ["/usr/bin/bash", "-p", "-c", script, "batch-global-preflight", str(tmp_path)],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()


def _probe_directory_scrubber() -> str:
    text = (HERE / "probe_registry_gate.sh").read_text()
    return text[text.index("mount_free_anchored_tree()") : text.index("preflight_exact_probe_file()")]


def _probe_cleanup_functions() -> str:
    text = (HERE / "probe_registry_gate.sh").read_text()
    return text[text.index("private_root_bound()") : text.index("early_cleanup()")]


def _probe_exact_file_scrubber() -> str:
    text = (HERE / "probe_registry_gate.sh").read_text()
    return text[text.index("preflight_exact_probe_file()") : text.index("close_probe_private_fds()")]


def test_tls_inode_is_armed_before_copy_and_signal_scrubs_partial_bytes(tmp_path: Path) -> None:
    probe = (HERE / "probe_registry_gate.sh").read_text()
    open_at = probe.index('exec {local_tls_fd}<>"$local_tls"')
    armed_at = probe.index("local_tls_identity=$(/usr/bin/stat -Lc '%d:%i'", open_at)
    copy_at = probe.index('/usr/bin/cp -- /proc/self/fd/4 "/proc/self/fd/$local_tls_fd"')
    assert open_at < armed_at < copy_at

    tls_copy = tmp_path / "tls-combined.pem"
    shell = (
        "set -euo pipefail\nGATE_EXPECTED_UID=$(id -u)\nlocal_tls=$1\n"
        'touch "$local_tls"; chmod 600 "$local_tls"; exec {local_tls_fd}<>"$local_tls"\n'
        "local_tls_identity=$(stat -Lc '%d:%i' /proc/self/fd/$local_tls_fd)\n"
        + _probe_exact_file_scrubber()
        + '\ntrap \'scrub_exact_probe_file "$local_tls_fd" "$local_tls_identity"; exit 130\' TERM\n'
        'printf partial-private-tls > "/proc/self/fd/$local_tls_fd"\nkill -TERM $$\n'
    )
    result = subprocess.run(
        ["/usr/bin/bash", "-p", "-c", shell, "tls-signal-test", str(tls_copy)],
        check=False,
        capture_output=True,
    )
    assert result.returncode == 130
    assert tls_copy.stat().st_size == 0


def test_early_cleanup_scrubs_tls_before_directory_descriptors_exist(tmp_path: Path) -> None:
    shell = (
        "set -euo pipefail\nshopt -u varredir_close\nGATE_EXPECTED_UID=$(id -u)\n"
        'private_root=$1/root\nmkdir -m 700 -- "$private_root"\n'
        'exec {private_root_fd}<"$private_root"\nprivate_root_anchor=/proc/self/fd/${private_root_fd}/.\n'
        "private_root_identity=$(stat -Lc '%d:%i:%a:%u' \"$private_root_anchor\")\n"
        "private_root_anchor_trusted=1\ncleanup_attempted=0\ncleanup_complete=0\n"
        "private_runtime_armed=0\npodman_guard_fd=-1\n"
        "private_dir_paths=()\nprivate_dir_fds=()\nprivate_dir_anchors=()\n"
        "private_dir_identities=()\nprivate_dir_manifests=()\n"
        'mkdir -m 700 -- "$private_root/graphroot" "$private_root/runroot" "$private_root/xdg-runtime" '
        '"$private_root/xdg-config" "$private_root/home" "$private_root/tmp"\n'
        "storage_conf=$private_root/storage.conf; local_tls=$private_root/tls-combined.pem; inspect_file=$private_root/inspect\n"
        'printf config > "$storage_conf"; printf partial-private-tls > "$local_tls"; : > "$inspect_file"\n'
        'chmod 600 "$storage_conf" "$local_tls" "$inspect_file"\n'
        'exec {storage_conf_fd}<>"$storage_conf" {local_tls_fd}<>"$local_tls" {inspect_fd}<>"$inspect_file"\n'
        "storage_conf_identity=$(stat -Lc '%d:%i' /proc/self/fd/$storage_conf_fd)\n"
        "local_tls_identity=$(stat -Lc '%d:%i' /proc/self/fd/$local_tls_fd)\n"
        "inspect_identity=$(stat -Lc '%d:%i' /proc/self/fd/$inspect_fd)\n"
        + _probe_cleanup_functions()
        + "\nset +e; scrub_private_contents; rc=$?; set -e\n"
        '[[ $rc -ne 0 && $(stat -c %s "$local_tls") == 0 ]]\n'
    )
    result = subprocess.run(
        ["/usr/bin/bash", "-p", "-c", shell, "early-tls-cleanup", str(tmp_path)],
        check=False,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()


def test_probe_retains_verified_scrubbed_root_and_child_directories(tmp_path: Path) -> None:
    script = (
        "set -euo pipefail\nshopt -u varredir_close\nGATE_EXPECTED_UID=$(id -u)\n"
        'private_root=$1/root\nmkdir -m 700 -- "$private_root"\n'
        'private_root_fd=-1\nexec {private_root_fd}<"$private_root"\n'
        "private_root_anchor=/proc/self/fd/${private_root_fd}/.\n"
        "private_root_identity=$(stat -Lc '%d:%i:%a:%u' \"$private_root_anchor\")\n"
        "private_root_anchor_trusted=1\ncleanup_attempted=0\nprivate_runtime_armed=1\n"
        "private_dir_paths=()\nprivate_dir_fds=()\nprivate_dir_anchors=()\nprivate_dir_identities=()\n"
        "private_dir_manifests=()\npodman_guard_fd=-1\n"
        "for name in graphroot runroot xdg-runtime xdg-config xdg-data home tmp; do\n"
        ' path="$private_root/$name"; mkdir -m 700 -- "$path"; printf secret > "$path/private"\n'
        ' exec {held}<"$path"; private_dir_paths+=("$path"); private_dir_fds+=("$held")\n'
        ' private_dir_anchors+=("/proc/self/fd/${held}/.")\n'
        " private_dir_identities+=(\"$(stat -Lc '%d:%i:%a:%u' /proc/self/fd/${held}/.)\")\n"
        " unset held\ndone\n"
        "storage_conf=$private_root/storage.conf\nlocal_tls=$private_root/tls-combined.pem\ninspect_file=$private_root/inspect\n"
        'printf config > "$storage_conf"; printf tls > "$local_tls"; printf inspect > "$inspect_file"\n'
        'chmod 600 "$storage_conf" "$local_tls" "$inspect_file"\n'
        'exec {storage_conf_fd}<>"$storage_conf" {local_tls_fd}<>"$local_tls" {inspect_fd}<>"$inspect_file"\n'
        'chmod 500 "$local_tls"\n'
        "storage_conf_identity=$(stat -Lc '%d:%i' /proc/self/fd/$storage_conf_fd)\n"
        "local_tls_identity=$(stat -Lc '%d:%i' /proc/self/fd/$local_tls_fd)\n"
        "inspect_identity=$(stat -Lc '%d:%i' /proc/self/fd/$inspect_fd)\n"
        + _probe_cleanup_functions()
        + "\nretain_private_root\n"
        '[[ -d "$private_root" && ! -L "$private_root" ]]\n'
        'for path in "${private_dir_paths[@]}"; do [[ -d "$path" && -z "$(find "$path" -mindepth 1 -print -quit)" ]]; done\n'
        '[[ $(stat -c %s "$storage_conf") == 0 && $(stat -c %s "$local_tls") == 0 && $(stat -c %s "$inspect_file") == 0 ]]\n'
        "[[ $private_root_fd == -1 && $storage_conf_fd == -1 && $local_tls_fd == -1 && $inspect_fd == -1 ]]\n"
    )
    result = subprocess.run(["/usr/bin/bash", "-p", "-c", script, "probe-retain", str(tmp_path)], capture_output=True)
    assert result.returncode == 0, result.stderr.decode()


@pytest.mark.parametrize("directory_name", ["graphroot", "runroot"])
def test_probe_scrubs_moved_podman_directory_by_fd_and_preserves_replacement(
    tmp_path: Path, directory_name: str
) -> None:
    script = (
        "set -euo pipefail\n"
        "GATE_EXPECTED_UID=$(id -u)\n"
        "original=$1/$2\nmoved=$1/moved-$2\nreplacement=$1/$2\n"
        'mkdir -m 700 -- "$original"\nmkdir "$original/nested"\nprintf secret > "$original/nested/private"\n'
        'exec {held_fd}<"$original"\nanchor=/proc/self/fd/${held_fd}/.\n'
        "identity=$(stat -Lc '%d:%i:%a:%u' \"$anchor\")\n"
        + _probe_directory_scrubber()
        + '\nmv "$original" "$moved"\nmkdir -m 700 -- "$replacement"\nprintf keep > "$replacement/sentinel"\n'
        'manifest=$(preflight_anchored_directory "$anchor" "$identity")\n'
        'scrub_anchored_directory "$anchor" "$identity" "$manifest"\n'
        '[[ -z "$(find "$moved" -mindepth 1 -print -quit)" ]]\n'
        '[[ $(<"$replacement/sentinel") == keep ]]\nexec {held_fd}<&-\n'
    )
    result = subprocess.run(
        ["/usr/bin/bash", "-p", "-c", script, "anchor-test", str(tmp_path), directory_name], capture_output=True
    )
    assert result.returncode == 0, result.stderr.decode()


def test_probe_preflight_rejects_hardlinks_and_specials_before_mutation(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    private = root / "private"
    private.write_text("secret")
    outside = tmp_path / "outside"
    os.link(private, outside)
    os.mkfifo(root / "fifo", mode=0o600)
    script = (
        "set -euo pipefail\nGATE_EXPECTED_UID=$(id -u)\nroot=$1\n"
        'exec {held_fd}<"$root"\nanchor=/proc/self/fd/${held_fd}/.\n'
        "identity=$(stat -Lc '%d:%i:%a:%u' \"$anchor\")\n"
        + _probe_directory_scrubber()
        + '\nset +e; preflight_anchored_directory "$anchor" "$identity" >/dev/null; rc=$?; set -e\n'
        '[[ $rc -ne 0 ]]\n[[ $(<"$root/private") == secret ]]\n'
        '[[ -p "$root/fifo" ]]\nexec {held_fd}<&-\n'
    )
    result = subprocess.run(["/usr/bin/bash", "-p", "-c", script, "preflight-test", str(root)], capture_output=True)
    assert result.returncode == 0, result.stderr.decode()
    assert outside.read_text() == "secret"


def test_probe_manifest_recheck_rejects_swap_before_mutation(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    private = root / "private"
    private.write_text("original-secret")
    script = (
        "set -euo pipefail\nGATE_EXPECTED_UID=$(id -u)\nroot=$1/root\n"
        'exec {held_fd}<"$root"\nanchor=/proc/self/fd/${held_fd}/.\n'
        "identity=$(stat -Lc '%d:%i:%a:%u' \"$anchor\")\n"
        + _probe_directory_scrubber()
        + '\nmanifest=$(preflight_anchored_directory "$anchor" "$identity")\n'
        'mv "$root/private" "$1/moved"\nprintf replacement > "$root/private"\n'
        'set +e; scrub_anchored_directory "$anchor" "$identity" "$manifest"; rc=$?; set -e\n'
        '[[ $rc -ne 0 && $(<"$root/private") == replacement && $(<"$1/moved") == original-secret ]]\n'
    )
    result = subprocess.run(
        ["/usr/bin/bash", "-p", "-c", script, "manifest-swap", str(tmp_path)],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()


def test_mount_table_check_rejects_exact_mountpoint() -> None:
    script = (
        "set -euo pipefail\nGATE_EXPECTED_UID=$(id -u)\n"
        + _probe_directory_scrubber()
        + "\nset +e; mount_free_anchored_tree /proc; rc=$?; set -e\n[[ $rc -ne 0 ]]\n"
    )
    result = subprocess.run(
        ["/usr/bin/bash", "-p", "-c", script, "mount-test"],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()


def test_global_preflight_rejects_one_bad_tree_before_mutating_any_target(tmp_path: Path) -> None:
    script = (
        "set -euo pipefail\nshopt -u varredir_close\nGATE_EXPECTED_UID=$(id -u)\n"
        'private_root=$1/root\nmkdir -m 700 -- "$private_root"\n'
        'exec {private_root_fd}<"$private_root"\nprivate_root_anchor=/proc/self/fd/${private_root_fd}/.\n'
        "private_root_identity=$(stat -Lc '%d:%i:%a:%u' \"$private_root_anchor\")\n"
        "private_root_anchor_trusted=1\ncleanup_attempted=0\ncleanup_complete=0\n"
        "private_runtime_armed=1\npodman_guard_fd=-1\n"
        "private_dir_paths=()\nprivate_dir_fds=()\nprivate_dir_anchors=()\n"
        "private_dir_identities=()\nprivate_dir_manifests=()\n"
        "for name in graphroot runroot xdg-runtime xdg-config xdg-data home tmp; do\n"
        ' path="$private_root/$name"; mkdir -m 700 -- "$path"; printf secret > "$path/private"\n'
        ' exec {held}<"$path"; private_dir_paths+=("$path"); private_dir_fds+=("$held")\n'
        ' private_dir_anchors+=("/proc/self/fd/${held}/.")\n'
        " private_dir_identities+=(\"$(stat -Lc '%d:%i:%a:%u' /proc/self/fd/${held}/.)\")\n"
        " unset held\ndone\n"
        "storage_conf=$private_root/storage.conf; local_tls=$private_root/tls-combined.pem; inspect_file=$private_root/inspect\n"
        'printf config > "$storage_conf"; printf tls-secret > "$local_tls"; printf inspect > "$inspect_file"\n'
        'chmod 600 "$storage_conf" "$local_tls" "$inspect_file"\n'
        'exec {storage_conf_fd}<>"$storage_conf" {local_tls_fd}<>"$local_tls" {inspect_fd}<>"$inspect_file"\n'
        "storage_conf_identity=$(stat -Lc '%d:%i' /proc/self/fd/$storage_conf_fd)\n"
        "local_tls_identity=$(stat -Lc '%d:%i' /proc/self/fd/$local_tls_fd)\n"
        "inspect_identity=$(stat -Lc '%d:%i' /proc/self/fd/$inspect_fd)\n"
        + _probe_cleanup_functions()
        + '\nmkfifo "$private_root/tmp/reject-fifo"\n'
        "set +e; scrub_private_contents; rc=$?; set -e\n"
        '[[ $rc -ne 0 && $(<"$private_root/graphroot/private") == secret ]]\n'
        '[[ $(<"$local_tls") == tls-secret && -p "$private_root/tmp/reject-fifo" ]]\n'
    )
    result = subprocess.run(
        ["/usr/bin/bash", "-p", "-c", script, "global-preflight", str(tmp_path)],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()


def test_cleanup_retains_roots_and_binds_every_podman_directory() -> None:
    batch = (HERE / "run_registry_gate.sbatch").read_text()
    probe = (HERE / "probe_registry_gate.sh").read_text()
    assert "/usr/bin/rmdir" not in batch and "/usr/bin/rmdir" not in probe
    assert "/usr/bin/rm -r" not in batch and "/usr/bin/rm -r" not in probe
    assert "retain_batch_root" in batch and "retain_private_root" in probe
    assert 'private_dir_paths=("$graphroot" "$runroot"' in probe
    assert "private_dirs_bound || blocked" in probe
    assert probe.count("private_dirs_bound || blocked") >= 14
    assert 'exec {auth_fd}<>"$auth_path"' in probe
    assert '/usr/bin/truncate -s 0 -- "/proc/self/fd/$auth_fd"' in probe
    assert "done < /proc/self/mountinfo" in batch
    assert "done < /proc/self/mountinfo" in probe
    storage_block = probe[probe.index("readonly graphroot=") : probe.index("cleanup_private_tree()")]
    assert 'graphroot = "%s"' in storage_block and 'runroot = "%s"' in storage_block
    assert 'rootless_storage_path = "%s"' in storage_block
    assert '"$graphroot" "$runroot" "$graphroot"' in storage_block
    assert (
        "/proc/self/fd"
        not in storage_block[
            storage_block.index("/usr/bin/printf '[storage]") : storage_block.index(
                '/usr/bin/chmod 600 "$storage_conf"'
            )
        ]
    )


@pytest.mark.parametrize(
    ("store", "expected_category"),
    [
        ("", "podman_info_shape"),
        ("/graph|/run", "podman_info_shape"),
        ("/graph|/run|overlay|extra", "podman_info_shape"),
        ("/graph|/run|overlay\nextra", "podman_info_shape"),
        ("x" * 4097, "podman_info_shape"),
        ("/wrong|/run|overlay", "podman_info_graphroot"),
        ("/graph|/wrong|overlay", "podman_info_runroot"),
        ("/graph|/run|vfs", "podman_info_driver"),
    ],
)
def test_podman_store_validation_has_only_fixed_categories(store: str, expected_category: str) -> None:
    probe = (HERE / "probe_registry_gate.sh").read_text()
    helper_start = probe.index("validate_podman_store() {")
    helper_end = probe.index("\n}\n", helper_start) + 3
    helper = probe[helper_start:helper_end]
    script = f"""set -euo pipefail
blocked() {{ /usr/bin/printf 'gate_category=%s\\n' \"$1\" >&2; exit 2; }}
{helper}
validate_podman_store \"$1\" /graph /run
"""
    result = subprocess.run(
        ["/usr/bin/bash", "-p", "-c", script, "store-test", store],
        capture_output=True,
    )
    assert result.returncode == 2
    assert result.stdout == b""
    assert result.stderr == f"gate_category={expected_category}\n".encode()


def test_podman_store_validation_accepts_exact_private_store() -> None:
    probe = (HERE / "probe_registry_gate.sh").read_text()
    helper_start = probe.index("validate_podman_store() {")
    helper_end = probe.index("\n}\n", helper_start) + 3
    helper = probe[helper_start:helper_end]
    script = f"""set -euo pipefail
blocked() {{ exit 2; }}
{helper}
validate_podman_store "$1" /graph /run
"""
    result = subprocess.run(
        ["/usr/bin/bash", "-p", "-c", script, "store-test", "/graph|/run|overlay"],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout == b"" and result.stderr == b""


@pytest.mark.parametrize(
    ("status", "expected_returncode", "expected_category"),
    [
        ("1", 0, None),
        ("0", 2, "podman_cold_present"),
        ("2", 2, "podman_image_exists_command"),
        ("125", 2, "podman_image_exists_command"),
    ],
)
def test_cold_image_status_has_only_fixed_categories(
    status: str, expected_returncode: int, expected_category: str | None
) -> None:
    probe = (HERE / "probe_registry_gate.sh").read_text()
    helper_start = probe.index("validate_cold_image_state() {")
    helper_end = probe.index("\n}\n", helper_start) + 3
    helper = probe[helper_start:helper_end]
    script = f"""set -euo pipefail
blocked() {{ /usr/bin/printf 'gate_category=%s\\n' \"$1\" >&2; exit 2; }}
{helper}
validate_cold_image_state \"$1\"
"""
    result = subprocess.run(
        ["/usr/bin/bash", "-p", "-c", script, "cold-test", status],
        capture_output=True,
    )
    assert result.returncode == expected_returncode
    assert result.stdout == b""
    expected = b"" if expected_category is None else f"gate_category={expected_category}\n".encode()
    assert result.stderr == expected


def test_every_source_login_and_pull_attempt_uses_exact_guard_descriptor() -> None:
    probe = (HERE / "probe_registry_gate.sh").read_text()
    guard = (HERE / "podman_guard.sh").read_text()
    worker = controller.WORKER.read_text()
    assert worker.count("podman login --authfile") == 1
    assert worker.count('podman pull "${auth_args[@]}"') == 1
    assert "/usr/bin/podman login" not in worker
    assert "/usr/bin/podman pull" not in worker
    assert '/usr/bin/ln -s -- "/proc/self/fd/$podman_guard_fd" "$podman_guard_alias"' in probe
    assert "export PATH=$private_tmp:/usr/bin:/bin" in probe
    assert "GATE_PODMAN_GUARD_IDENTITY" in probe
    call = '/usr/bin/podman "$@"'
    assert guard.count(call) == 1
    call_at = guard.index(call)
    assert guard.rfind("private_dirs_bound || exit 125", 0, call_at) >= 0
    assert guard.index("private_dirs_bound || exit 125", call_at) > call_at
    assert '[[ $# -ge 1 && ( "$1" == login || "$1" == pull )' in guard


def test_exact_guard_fd_executes_and_validates_around_no_network_help(tmp_path: Path) -> None:
    if os.getuid() != controller.OWNER_UID:
        pytest.skip("the frozen guard intentionally binds the production uid")
    source_guard = HERE / "podman_guard.sh"
    guard = tmp_path / "podman_guard.sh"
    guard.write_bytes(source_guard.read_bytes())
    guard.chmod(0o500)
    private_root = tmp_path / "root"
    private_root.mkdir(mode=0o700)
    directories = []
    for name in ("graphroot", "runroot", "xdg-runtime", "xdg-config", "xdg-data", "home", "tmp"):
        path = private_root / name
        path.mkdir(mode=0o700)
        directories.append(path)

    guard_fd = os.open(guard, os.O_RDONLY)
    root_fd = os.open(private_root, os.O_RDONLY | os.O_DIRECTORY)
    directory_fds = [os.open(path, os.O_RDONLY | os.O_DIRECTORY) for path in directories]
    alias = directories[-1] / "podman"
    alias.symlink_to(f"/proc/self/fd/{guard_fd}")
    try:
        root_info = os.fstat(root_fd)
        guard_info = os.fstat(guard_fd)
        env = {
            "HOME": str(directories[-2]),
            "PATH": f"{directories[-1]}:/usr/bin:/bin",
            "GATE_PRIVATE_ROOT_PATH": str(private_root),
            "GATE_PRIVATE_ROOT_ANCHOR": f"/proc/self/fd/{root_fd}/.",
            "GATE_PRIVATE_ROOT_IDENTITY": (
                f"{root_info.st_dev}:{root_info.st_ino}:{stat.S_IMODE(root_info.st_mode):o}:{root_info.st_uid}"
            ),
            "GATE_PODMAN_GUARD_FD": str(guard_fd),
            "GATE_PODMAN_GUARD_IDENTITY": (
                f"{guard_info.st_dev}:{guard_info.st_ino}:{stat.S_IMODE(guard_info.st_mode):o}:"
                f"{guard_info.st_uid}:{guard_info.st_nlink}"
            ),
            "GATE_PODMAN_GUARD_SHA256": hashlib.sha256(guard.read_bytes()).hexdigest(),
            "GATE_PODMAN_GUARD_ALIAS": str(alias),
        }
        for index, (path, fd) in enumerate(zip(directories, directory_fds, strict=True)):
            info = os.fstat(fd)
            env[f"GATE_PRIVATE_PATH_{index}"] = str(path)
            env[f"GATE_PRIVATE_ANCHOR_{index}"] = f"/proc/self/fd/{fd}/."
            env[f"GATE_PRIVATE_IDENTITY_{index}"] = (
                f"{info.st_dev}:{info.st_ino}:{stat.S_IMODE(info.st_mode):o}:{info.st_uid}"
            )
        result = subprocess.run(
            ["/usr/bin/timeout", "2s", str(alias), "login", "--help"],
            env=env,
            pass_fds=(guard_fd, root_fd, *directory_fds),
            check=False,
            capture_output=True,
        )
    finally:
        for fd in directory_fds:
            os.close(fd)
        os.close(root_fd)
        os.close(guard_fd)
    assert result.returncode == 0


def test_guard_signal_ladder_kills_and_reaps_term_ignoring_child() -> None:
    guard = (HERE / "podman_guard.sh").read_text()
    stop_function = guard[guard.index("process_identity()") : guard.index("trap 'forward_signal 129'")]
    shell = (
        "set -euo pipefail\nGATE_EXPECTED_UID=$(id -u)\n"
        + stop_function
        + "\n/usr/bin/bash -c 'trap \"\" TERM; exec /usr/bin/sleep 30' &\n"
        "child=$!\n"
        "/usr/bin/sleep 0.2\n"
        'identity=$(process_identity "$child")\n'
        'stop_and_reap_child "$child" "$identity"\n'
        '[[ ! -e "/proc/$child" ]]\n'
    )
    started = time.monotonic()
    result = subprocess.run(
        ["/usr/bin/bash", "-p", "-c", shell, "guard-signal-test"],
        check=False,
        capture_output=True,
    )
    elapsed = time.monotonic() - started
    assert result.returncode == 0, result.stderr.decode()
    assert 1.5 <= elapsed < 4.0


def test_probe_preflight_checks_device_owner_type_and_links() -> None:
    scrub = _probe_directory_scrubber()
    assert "'%D:%i:%U:%y:%n:%p\\n'" in scrub
    assert '"$dev" == "$root_dev"' in scrub
    assert '"$uid" == "${GATE_EXPECTED_UID}"' in scrub
    assert 'f|l) [[ "$links" == 1 ]]' in scrub
    assert "*) return 1" in scrub
    assert "done < /proc/self/mountinfo" in scrub


def test_signal_grace_exceeds_anchored_cleanup_bound() -> None:
    batch = (HERE / "run_registry_gate.sbatch").read_text()
    probe = (HERE / "probe_registry_gate.sh").read_text()
    guard = (HERE / "podman_guard.sh").read_text()
    assert "for _ in {1..1600}" in batch
    assert "for _ in {1..50}" in batch
    assert "--kill-after=150s 1560s" in batch
    assert "if (( spawning )); then" in batch
    assert "spawn_group_ready=0" in batch
    assert batch.count('wait "$active_pid"') == 1
    assert "--kill-after=3s 12s" in probe
    assert "--kill-after=3s 10s" in probe
    assert "--kill-after=3s 15s" in probe
    assert "--kill-after=5s 30s" in probe
    assert "--kill-after=1s 3s" in probe
    assert "/usr/bin/rm -r" not in batch
    assert "/usr/bin/rm -r" not in probe
    assert "/usr/bin/chmod -R" not in batch
    assert "/usr/bin/chmod -R" not in probe
    assert controller.PROBE_CLEANUP_BOUND_SECONDS < controller.OUTER_KILL_GRACE_SECONDS
    assert controller.OUTER_KILL_GRACE_SECONDS < controller.PARENT_TERM_GRACE_SECONDS
    assert controller.SIGNAL_TEARDOWN_BOUND_SECONDS < controller.SIGNAL_LEAD_SECONDS
    assert controller.SIGNAL_TEARDOWN_BOUND_SECONDS == 210
    assert batch.count("/usr/bin/timeout --signal=TERM --kill-after=2s 8s") == 2
    assert "/usr/bin/sleep 2" in guard
    assert '/usr/bin/kill -KILL -- "$child"' in guard
    assert 'wait "$child" 2>/dev/null' in guard


def test_worst_case_signal_timing_is_mathematically_nested() -> None:
    global_root_preflight_bound = 3 + 1
    global_directory_preflight_bound = 12 + 3
    directory_mutation_bound = (12 + 3) + (10 + 3) + (15 + 3) + (30 + 5) + (3 + 1)
    postflight_bound = 3 + 1
    exact_file_mutation_bound = (2 + 1) + (5 + 1)
    probe_failure_bound = (
        global_root_preflight_bound
        + global_directory_preflight_bound
        + max(directory_mutation_bound, exact_file_mutation_bound)
        + postflight_bound
    )
    batch_failure_bound = (3 + 1) + max(2 + 1 + 5 + 1, 0) + (3 + 1)
    # A successful sync returns before its soft deadline; a timeout stops the
    # publication chain, so two kill-after tails cannot accumulate.
    publication_success_bound = 2 * 8
    publication_timeout_bound = 8 + 2
    assert directory_mutation_bound == 85
    assert probe_failure_bound == 108
    assert controller.PODMAN_GUARD_SIGNAL_BOUND_SECONDS + probe_failure_bound <= controller.PROBE_CLEANUP_BOUND_SECONDS
    assert batch_failure_bound == 17 <= controller.BATCH_CLEANUP_BOUND_SECONDS
    assert publication_success_bound <= controller.RESULT_PUBLICATION_BOUND_SECONDS
    assert publication_timeout_bound <= controller.RESULT_PUBLICATION_BOUND_SECONDS
    assert controller.PROBE_CLEANUP_BOUND_SECONDS < controller.OUTER_KILL_GRACE_SECONDS
    assert controller.PARENT_TERM_GRACE_SECONDS + controller.PARENT_KILL_REAP_SECONDS == 165
    assert (
        controller.PARENT_TERM_GRACE_SECONDS
        + controller.PARENT_KILL_REAP_SECONDS
        + controller.BATCH_CLEANUP_BOUND_SECONDS
        + controller.RESULT_PUBLICATION_BOUND_SECONDS
        == controller.SIGNAL_TEARDOWN_BOUND_SECONDS
        < controller.SIGNAL_LEAD_SECONDS
    )


def test_probe_proves_cold_store_and_documented_absence_rc() -> None:
    text = (HERE / "probe_registry_gate.sh").read_text()
    assert text.count('/usr/bin/podman image exists "$GATE_IMAGE"') == 2
    assert 'validate_cold_image_state "$cold_exists_rc"' in text
    assert "0) blocked podman_cold_present" in text
    assert "*) blocked podman_image_exists_command" in text
    assert "image_exists_rc != 1" in text


def test_launcher_arms_parent_death_signal() -> None:
    text = (HERE / "launch.sh").read_text()
    assert "prctl(1,signal.SIGTERM,0,0,0)" in text
    assert "if os.getppid()!=parent" in text


def test_controller_dict_literals_have_no_duplicate_string_keys() -> None:
    tree = ast.parse((HERE / "controller.py").read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = [key.value for key in node.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)]
        assert len(keys) == len(set(keys)), f"duplicate dict key at line {node.lineno}"


def test_compute_manifest_covers_all_reachable_gate_tools() -> None:
    rows = [line.split("  ", 1) for line in (HERE / "compute_tools.sha256").read_text().splitlines()]
    paths = {path for _digest, path in rows}
    required = {
        "/usr/bin/basename",
        "/usr/bin/dirname",
        "/usr/bin/printf",
        "/usr/bin/scontrol",
        "/usr/bin/squeue",
        "/usr/bin/srun",
    }
    assert required <= paths
    assert len(rows) == 32
    vector = json.dumps([digest for digest, _path in rows], separators=(",", ":")).encode()
    assert hashlib.sha256(vector).hexdigest() == controller.COMPUTE_TOOL_VECTOR_SHA256


@pytest.mark.parametrize(
    ("line", "rc", "expected"),
    [
        (
            "ERROR: private registry login failed with category=local-storage on attempt 1/8; "
            "The exact frozen image is unchanged",
            1,
            "login_local_storage",
        ),
        (
            "ERROR: private registry login exhausted 8 bounded attempts with category=dns; "
            "The exact frozen image is unchanged",
            1,
            "login_dns",
        ),
        (
            "ERROR: container image pull failed with category=authentication on attempt 1/3",
            1,
            "pull_authentication",
        ),
        (
            "ERROR: container image pull exhausted 3 bounded attempts with category=timeout",
            1,
            "pull_timeout",
        ),
        (
            "ERROR: private registry credential mint failed with category=credential-broker exit=1",
            1,
            "login_credential_broker",
        ),
        ("gate_category=podman_info_command", 2, "podman_info_command"),
        ("gate_category=podman_info_shape", 2, "podman_info_shape"),
        ("gate_category=podman_info_graphroot", 2, "podman_info_graphroot"),
        ("gate_category=podman_info_runroot", 2, "podman_info_runroot"),
        ("gate_category=podman_info_driver", 2, "podman_info_driver"),
        ("gate_category=podman_cold_present", 2, "podman_cold_present"),
        (
            "gate_category=podman_image_exists_command",
            2,
            "podman_image_exists_command",
        ),
        ("gate_category=compute_tools_identity", 2, "compute_tools_identity"),
        ("gate_category=registry_login_path", 2, "registry_login_path"),
        ("gate_category=registry_login_open", 2, "registry_login_open"),
        ("gate_category=registry_login_stat", 2, "registry_login_stat"),
        ("gate_category=registry_login_identity", 2, "registry_login_identity"),
        ("gate_stage=probe_entry", 2, "internal_after_probe_entry"),
        (
            "gate_stage=probe_entry\ngate_stage=source_bound\ngate_stage=podman_ready",
            2,
            "internal_after_podman_ready",
        ),
        (
            "gate_stage=declarations_bound\ngate_stage=metadata_bound\ngate_stage=descriptors_bound",
            2,
            "internal_after_descriptors_bound",
        ),
        (
            "gate_stage=file_hashes_bound\ngate_stage=manifest_bound\ngate_stage=tools_bound",
            2,
            "internal_after_tools_bound",
        ),
        ("gate_stage=tls_bound\ngate_stage=tls_fd_bound", 2, "internal_after_tls_fd_bound"),
        (
            "gate_stage=registry_enter\ngate_stage=worker_sourced\ngate_stage=login_returned",
            2,
            "internal_after_login_returned",
        ),
        (
            "gate_stage=auth_path_valid\ngate_stage=auth_opened\ngate_stage=auth_bound",
            2,
            "internal_after_auth_bound",
        ),
        ("gate_stage=pull_returned", 2, "internal_after_pull_returned"),
        (
            "gate_stage=podman_ready\nERROR: private registry login failed with category=authentication on attempt 1/8",
            1,
            "login_authentication",
        ),
        ("gate_stage=podman_ready", 143, "interrupted"),
        ("unclassified private text", 143, "interrupted"),
        ("unclassified private text", 1, "internal"),
    ],
)
def test_actual_shell_stderr_classification(tmp_path: Path, line: str, rc: int, expected: str) -> None:
    error_file = tmp_path / "stderr"
    error_file.write_text(line + "\n")
    error_file.chmod(0o600)
    script = HERE / "classify_registry_error.sh"
    result = subprocess.run(
        [
            "/usr/bin/bash",
            "-p",
            "-c",
            'source "$1"; classify_registry_error_file "$2" "$3"; printf "%s" "$REGISTRY_SAFE_CATEGORY"',
            "classifier-test",
            str(script),
            str(error_file),
            str(rc),
        ],
        check=False,
        capture_output=True,
    )
    assert result.returncode == 0
    assert result.stderr == b""
    assert result.stdout.decode() == expected


def test_exact_retained_stderr_descriptor_surfaces_login_authentication(tmp_path: Path) -> None:
    error_file = tmp_path / "stderr"
    error_file.write_text(
        "ERROR: private registry login failed with category=authentication on attempt 1/8; refusing to retry\n"
    )
    error_file.chmod(0o600)
    script = HERE / "classify_registry_error.sh"
    shell = (
        'source "$1"; exec {error_fd}<>"$2"; '
        "identity=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h' -- /proc/self/fd/$error_fd); "
        'classify_registry_error_file "/proc/self/fd/$error_fd" 1 "$identity"; '
        '/usr/bin/printf "%s" "$REGISTRY_SAFE_CATEGORY"'
    )
    result = subprocess.run(
        ["/usr/bin/bash", "-p", "-c", shell, "descriptor-classifier", str(script), str(error_file)],
        check=False,
        capture_output=True,
    )
    assert result.returncode == 0
    assert result.stderr == b""
    assert result.stdout == b"login_authentication"


def test_retained_stderr_descriptor_rejects_wrong_inode_binding(tmp_path: Path) -> None:
    error_file = tmp_path / "stderr"
    error_file.write_text("ERROR: private registry login failed with category=authentication\n")
    error_file.chmod(0o600)
    script = HERE / "classify_registry_error.sh"
    shell = (
        'source "$1"; exec {error_fd}<>"$2"; '
        'if classify_registry_error_file "/proc/self/fd/$error_fd" 1 "0:0:600:656177:1"; then exit 1; fi'
    )
    result = subprocess.run(
        ["/usr/bin/bash", "-p", "-c", shell, "descriptor-classifier", str(script), str(error_file)],
        check=False,
        capture_output=True,
    )
    assert result.returncode == 0
    assert result.stdout == b""
    assert result.stderr == b""


@pytest.mark.parametrize(
    "category",
    [
        "login_local_storage",
        "login_local_userns",
        "login_client_config",
        "pull_local_lock",
        "pull_authentication",
        "pull_timeout",
    ],
)
def test_safe_worker_categories_are_allowed(category: str) -> None:
    payload = {
        "category": category,
        "image_digest": controller.IMAGE_DIGEST,
        "kind": "k3-registry-pull-gate-v27",
        "platform": "linux/arm64",
        "state": "blocked",
    }
    raw = controller.canonical(payload)
    captured = controller.Capture(raw, controller.digest(raw), (0,) * 9)
    assert controller.validate_result_payload(captured, False)[1] == category


def test_public_success_log_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(controller, "LOG_ROOT", tmp_path)
    path = tmp_path / "slurm-12345.log"
    payload = {
        "category": "success",
        "image_digest": controller.IMAGE_DIGEST,
        "kind": "k3-registry-pull-gate-v27",
        "platform": "linux/arm64",
        "state": "complete",
    }
    path.write_bytes(controller.canonical(payload))
    path.chmod(0o600)
    captured = controller.stable_file(path, mode=0o600, maximum=4096)
    observed, category = controller.validate_result_payload(captured, True)
    assert observed == controller.digest(path.read_bytes())
    assert category == "success"


def test_public_log_rejects_extra_field(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(controller, "LOG_ROOT", tmp_path)
    path = tmp_path / "slurm-12345.log"
    payload = {
        "category": "success",
        "image_digest": controller.IMAGE_DIGEST,
        "kind": "k3-registry-pull-gate-v27",
        "platform": "linux/arm64",
        "state": "complete",
        "raw": "forbidden",
    }
    path.write_bytes(controller.canonical(payload))
    path.chmod(0o600)
    with pytest.raises(controller.GateError, match="public_log_contract"):
        captured = controller.stable_file(path, mode=0o600, maximum=4096)
        controller.validate_result_payload(captured, True)


def test_pending_is_not_launch_eligible() -> None:
    payload = controller.pending_contract({"controller": "f" * 64})
    assert payload["launch_eligible"] is False
    assert payload["state"] == "pending_independent_approval"


def test_pending_bytes_are_canonical_for_current_bundle() -> None:
    hashes = {
        key: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
        for key, (name, _mode) in controller.BUNDLE_FILES.items()
        if key != "pending"
    }
    assert (HERE / "pending.json").read_bytes() == controller.canonical(controller.pending_contract(hashes))


def test_controller_has_no_task_or_model_execution_imports() -> None:
    text = (HERE / "controller.py").read_text()
    assert "harbor" not in text.lower()
    assert "container_run(" not in text
    assert "podman run" not in text


def test_no_approval_is_shipped() -> None:
    assert not any("approval" in path.name for path in HERE.iterdir())
