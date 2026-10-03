from __future__ import annotations

import ast
import fcntl
import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("registry_gate_v14_controller", HERE / "controller.py")
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
    assert contract["scheduler"]["time"] == "00:30:00"


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
    assert command.count("--cpus-per-task=4") == 1
    assert command.count("--mem=16G") == 1
    assert command.count("--time=00:30:00") == 1
    assert command.count("--no-requeue") == 1
    assert command.count("--signal=B:TERM@120") == 1
    assert [part for part in command if part.startswith("--export")] == ["--export-file=/private/environment.bin"]
    assert str(controller.BUNDLE / "run_registry_gate.sbatch") not in command
    assert command[-2:] == ["--export-file=/private/environment.bin", "-"]


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


def test_submit_retries_transient_name_query_without_resubmit(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = "12345"
    calls = {"submit": 0, "query": 0, "stable": 0}
    batch_raw = b"#!/usr/bin/bash\nexit 0\n"
    submitted: dict[str, object] = {}

    def fake_submit(*_args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls["submit"] += 1
        stdin = kwargs["stdin"]
        assert isinstance(stdin, int)
        submitted["raw"] = os.read(stdin, len(batch_raw) + 1)
        submitted["seals"] = fcntl.fcntl(stdin, fcntl.F_GET_SEALS)
        return subprocess.CompletedProcess([], 0, f"{job_id}\n".encode(), b"")

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
    monkeypatch.setattr(controller.subprocess, "run", fake_submit)
    monkeypatch.setattr(controller, "queue_name_ids", fake_query)
    monkeypatch.setattr(controller, "stable_reads", fake_stable)
    monkeypatch.setattr(controller.time, "sleep", lambda _seconds: None)
    assert controller.submit_once(Path("/private/environment"), "a" * 24, batch_raw) == job_id
    assert calls == {"submit": 1, "query": 3, "stable": 1}
    assert submitted["raw"] == batch_raw
    assert submitted["seals"] == (fcntl.F_SEAL_SEAL | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_GROW | fcntl.F_SEAL_WRITE)
    assert job_id in controller.OWNED_JOB_IDS


def test_direct_id_is_retained_before_submission_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = "12345"
    monkeypatch.setattr(controller, "SUBMITTED_JOB_ID", None)
    monkeypatch.setattr(controller, "OWNED_JOB_IDS", set())
    monkeypatch.setattr(
        controller.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, f"{job_id}\n".encode(), b""),
    )
    monkeypatch.setattr(controller, "queue_name_ids", lambda: {job_id, "12346"})
    with pytest.raises(controller.GateError, match="submission_conflict"):
        controller.submit_once(Path("/private/environment"), "a" * 24, b"#!/usr/bin/bash\nexit 0\n")
    assert controller.SUBMITTED_JOB_ID == job_id
    assert job_id in controller.OWNED_JOB_IDS


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


def test_batch_has_one_production_shaped_srun() -> None:
    text = (HERE / "run_registry_gate.sbatch").read_text()
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


def test_batch_public_output_is_only_emit() -> None:
    text = (HERE / "run_registry_gate.sbatch").read_text()
    assert "raw=$(/usr/bin/printf" in text
    assert '/usr/bin/printf \'%s\' "$raw" > "$temp"' in text
    assert "/usr/bin/printf '%s' \"$raw\" | /usr/bin/sha256sum" in text
    assert text.count("\n    /usr/bin/printf '%s' \"$raw\" >&8\n") == 1
    assert "exec 8>&1 4>&2 >/dev/null 2>/dev/null" in text
    assert '>"$stdout" 2>"$stderr"' in text
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
    assert '/usr/bin/bash -p -s >"$stdout" 2>"$stderr" < /proc/self/fd/6' in batch
    assert "source /proc/self/fd/8" in probe
    assert "source /proc/self/fd/9" in probe
    assert 'exec 9<"$worker" 8<"$aws_creds" 7<"$tools_manifest"' in probe


def test_cleanup_traps_precede_first_mktemp() -> None:
    batch = (HERE / "run_registry_gate.sbatch").read_text()
    probe = (HERE / "probe_registry_gate.sh").read_text()
    assert batch.index("trap early_cleanup EXIT") < batch.index("private=$(/usr/bin/mktemp")
    assert probe.index("trap early_cleanup EXIT") < probe.index("private_root=$(/usr/bin/mktemp")


def test_private_cleanup_makes_read_only_files_writable_before_truncation() -> None:
    batch = (HERE / "run_registry_gate.sbatch").read_text()
    probe = (HERE / "probe_registry_gate.sh").read_text()
    assert batch.index('/usr/bin/chmod 600 -- "$local_tools"') < batch.index('/usr/bin/truncate -s 0 -- "$local_tools"')
    cleanup = probe[probe.index("cleanup_private_tree()") : probe.index("\ncleanup() {")]
    chmod = cleanup.index("-exec /usr/bin/chmod u+rwx")
    truncate = cleanup.index("-exec /usr/bin/truncate")
    assert chmod < truncate
    assert "-type f -links 1" in cleanup


def test_probe_proves_cold_store_and_documented_absence_rc() -> None:
    text = (HERE / "probe_registry_gate.sh").read_text()
    assert text.count('/usr/bin/podman image exists "$GATE_IMAGE"') == 2
    assert "cold_exists_rc != 1" in text
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
    paths = {line.split("  ", 1)[1] for line in (HERE / "compute_tools.sha256").read_text().splitlines()}
    required = {
        "/usr/bin/basename",
        "/usr/bin/dirname",
        "/usr/bin/printf",
        "/usr/bin/scontrol",
        "/usr/bin/squeue",
        "/usr/bin/srun",
    }
    assert required <= paths


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
        ("gate_category=podman_info", 2, "podman_info"),
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
        "kind": "k3-registry-pull-gate-v14",
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
        "kind": "k3-registry-pull-gate-v14",
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
        "kind": "k3-registry-pull-gate-v14",
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
