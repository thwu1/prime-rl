from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from types import SimpleNamespace

import dispatch_known_cost_eval as dispatch
import pytest
import run_known_cost_eval_task as runner


def _authority(tmp_path: Path, *, task_count: int = 6) -> dict[str, object]:
    plan = {
        "plan_id": "a" * 64,
        "plan_root": str((tmp_path / "plan").resolve()),
        "eval_root": str((tmp_path / "eval").resolve()),
        "implementations": {
            "planner": {
                "repository_path": "user/tianhaowu/rsci/materialize_known_cost_eval_plan.py",
                "path": "/planner",
                "size_bytes": 1,
                "sha256": "7" * 64,
            }
        },
        "tasks": [],
    }
    tasks = []
    for index in range(task_count):
        task_id = f"task-{index}"
        tasks.append(
            {
                "task_id": task_id,
                "model_key": f"model-{index}",
                "config_bundle_sha256": f"{index + 1:064x}",
                "checkpoint_inventory_sha256": f"{index + 11:064x}",
                "result_root": str((tmp_path / "plan" / "results" / task_id).resolve()),
                "receipt_dir": str((tmp_path / "plan" / "receipts" / task_id).resolve()),
            }
        )
    plan["tasks"] = tasks
    plan_path = (tmp_path / "plan" / "plan.json").resolve()
    context = runner.PlanContext(plan, plan_path, "b" * 64, tmp_path / "old-source", {})
    execution_root = tmp_path / "execution" / "source_snapshot"
    execution_source = {
        "run_dir": str(execution_root.parent.resolve()),
        "snapshot_path": str(execution_root.resolve()),
        "parent_commit_sha": "c" * 40,
        "source_tree_sha256": "d" * 64,
        "provenance_manifest": {"path": "/provenance", "size_bytes": 1, "sha256": "e" * 64},
        "runner": {
            "repository_path": str(dispatch.RUNNER_REPOSITORY_PATH),
            "path": str(execution_root / dispatch.RUNNER_REPOSITORY_PATH),
            "size_bytes": 10,
            "sha256": "f" * 64,
        },
        "dispatcher": {
            "repository_path": str(dispatch.SCRIPT_REPOSITORY_PATH),
            "path": str(execution_root / dispatch.SCRIPT_REPOSITORY_PATH),
            "size_bytes": 20,
            "sha256": "1" * 64,
        },
    }
    return {
        "plan_context": context,
        "plan_identity": {"path": str(plan_path), "size_bytes": 1, "sha256": "b" * 64},
        "launch_intent": {"path": "/launch", "size_bytes": 1, "sha256": "2" * 64},
        "postrun_authority": {"path": "/postrun", "size_bytes": 1, "sha256": "3" * 64},
        "execution_source": execution_source,
        "state_root": (tmp_path / "dispatch" / plan["plan_id"]).resolve(),
        "task_by_id": {task["task_id"]: task for task in tasks},
        "job_names": {task["task_id"]: dispatch.scheduler_job_name(plan, task["task_id"]) for task in tasks},
        "account": "ram",
        "qos": dispatch.REQUIRED_QOS,
        "control_tmux": {"socket": "/tmp/control.sock", "session": "control", "window": "Launcher"},
    }


def _materialize_terminal_attempt(
    tmp_path: Path,
    *,
    recovered: bool,
    succeeded: bool = False,
) -> tuple[dict[str, object], dict[str, Path]]:
    if recovered and succeeded:
        raise ValueError("A scheduler-recovered receipt cannot succeed")
    authority = _authority(tmp_path, task_count=1)
    plan = authority["plan_context"].plan
    plan_path = authority["plan_context"].plan_path
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_bytes(runner.canonical_json_bytes(plan))
    plan_path.chmod(0o444)
    authority["plan_context"] = runner.PlanContext(
        plan,
        plan_path,
        runner.file_sha256(plan_path),
        tmp_path / "old-source",
        {},
    )
    authority["plan_identity"] = runner.file_identity(plan_path)
    authority["execution_source"]["runner"] = {
        "repository_path": str(dispatch.RUNNER_REPOSITORY_PATH),
        **runner.file_identity(Path(runner.__file__)),
    }

    task = authority["task_by_id"]["task-0"]
    task_plan = dispatch.build_task_plan(authority, task, 1)
    paths = {key: Path(value) for key, value in task_plan["paths"].items()}
    global_path = authority["state_root"] / dispatch.GLOBAL_INTENT_NAME
    dispatch._write_json_once_atomic(
        global_path,
        dispatch.global_intent(authority, "2026-08-08T00:00:00Z"),
        "global intent",
    )
    dispatch._write_bytes_once_atomic(
        Path(task_plan["sbatch"]["path"]),
        task_plan["sbatch_content"],
        "batch script",
    )
    batch = dispatch.batch_intent(
        global_path=global_path,
        plans=[task_plan],
        created_at="2026-08-08T00:00:01Z",
    )
    batch_path = dispatch._batch_path(authority["state_root"], batch)
    dispatch._write_json_once_atomic(batch_path, batch, "batch intent")
    intent = dispatch.task_intent(
        authority=authority,
        plan=task_plan,
        global_path=global_path,
        batch_path=batch_path,
        created_at="2026-08-08T00:00:02Z",
    )
    dispatch._write_json_once_atomic(paths["intent"], intent, "task intent")
    job_id = 123
    scheduler_record = {
        "job_id": job_id,
        "comment": task_plan["comment"],
        "job_name": task_plan["scheduler"]["job_name"],
        "account": task_plan["scheduler"]["account"],
        "qos": task_plan["scheduler"]["qos"],
    }
    evidence = {
        "command": ["scontrol", "show", "job", str(job_id), "--oneliner"],
        "stdout_sha256": "8" * 64,
        "submitted_batch_script_sha256": task_plan["sbatch"]["sha256"],
        "record": scheduler_record,
    }
    submission = dispatch.submission_receipt(
        plan=task_plan,
        intent_path=paths["intent"],
        job_id=job_id,
        source="sbatch_stdout",
        sbatch_stdout=str(job_id),
        scheduler_evidence=evidence,
    )
    dispatch._write_json_once_atomic(paths["receipt"], submission, "submission receipt")

    if recovered:
        terminal_scheduler = {
            "job_id": str(job_id),
            "array_task_id": None,
            "comment": task_plan["comment"],
            "job_name": task_plan["scheduler"]["job_name"],
            "account": task_plan["scheduler"]["account"],
            "qos": task_plan["scheduler"]["qos"],
            "submitted_batch_script_sha256": task_plan["sbatch"]["sha256"],
            "terminal_state": "NODE_FAIL",
            "terminal_exit_code": "1:0",
            "submit_time": "2026-08-08T00:00:03",
            "start_time": "2026-08-08T00:00:04",
            "end_time": "2026-08-08T00:01:00",
            "elapsed_seconds": 56,
            "recovered_plan_status": "failed",
            "terminal_query": {
                "queried_at": "2026-08-08T00:01:01Z",
                "squeue_command": [
                    "squeue",
                    "--noheader",
                    "--jobs",
                    str(job_id),
                    f"--format={dispatch.SQUEUE_FORMAT}",
                ],
                "squeue_stdout_sha256": "9" * 64,
                "sacct_command": [
                    "sacct",
                    "--noheader",
                    "--parsable2",
                    "--allocations",
                    "--jobs",
                    str(job_id),
                    f"--format={','.join(dispatch.TERMINAL_SACCT_FIELDS)}",
                ],
                "sacct_stdout_sha256": "a" * 64,
            },
        }
        context, terminal_receipt = dispatch.recovered_terminal_receipt(
            authority=authority,
            task=task,
            submission={"plan": task_plan, "receipt": submission},
            terminal=terminal_scheduler,
        )
    else:
        scheduler = {
            "job_id": str(job_id),
            "array_task_id": None,
            "comment": task_plan["comment"],
            "job_name": task_plan["scheduler"]["job_name"],
            "account": task_plan["scheduler"]["account"],
            "qos": task_plan["scheduler"]["qos"],
            "submitted_batch_script_sha256": task_plan["sbatch"]["sha256"],
        }
        receipt_path = Path(task["receipt_dir"]) / "attempt_0001.json"
        context = runner.AttemptContext(
            plan_context=authority["plan_context"],
            task=task,
            attempt=1,
            receipt_path=receipt_path,
            predecessor_receipt_sha256=None,
            scheduler=scheduler,
            dispatch_intent=runner.file_identity(paths["intent"]),
        )
        if succeeded:
            terminal_receipt = runner.build_terminal_receipt(
                context,
                status="succeeded",
                started_at="2026-08-08T00:00:04Z",
                finished_at="2026-08-08T00:01:00Z",
                exit_code=0,
                shards=[],
            )
        else:
            terminal_receipt = runner.build_terminal_receipt(
                context,
                status="failed",
                started_at="2026-08-08T00:00:04Z",
                finished_at="2026-08-08T00:01:00Z",
                exit_code=1,
                failure="RuntimeError: test failure",
            )
    context.receipt_path.parent.mkdir(parents=True, exist_ok=True)
    context.receipt_path.write_bytes(runner.canonical_json_bytes(terminal_receipt))
    context.receipt_path.chmod(0o444)
    return authority, {**paths, "terminal": context.receipt_path}


def _terminal_allocation(
    job_id: int,
    plan: dict[str, object],
    *,
    state: str,
    exit_code: str,
) -> dict[str, object]:
    sacct_stdout = (
        f"{job_id}|{plan['scheduler']['job_name']}|{state}|{exit_code}|"
        f"{plan['scheduler']['account']}|{plan['scheduler']['qos']}|{plan['comment']}|\n"
    )
    return {
        "queried_at": "2026-08-08T00:02:00Z",
        "sacct_command": [
            "sacct",
            "--noheader",
            "--parsable2",
            "--allocations",
            "--jobs",
            str(job_id),
            f"--format={dispatch.VALIDATION_SACCT_FORMAT}",
        ],
        "sacct_stdout": sacct_stdout,
        "sacct_stdout_sha256": hashlib.sha256(sacct_stdout.encode()).hexdigest(),
        "submitted_batch_script_command": ["scontrol", "write", "batch_script", str(job_id), "-"],
        "record": {
            "job_id": str(job_id),
            "comment": plan["comment"],
            "job_name": plan["scheduler"]["job_name"],
            "account": plan["scheduler"]["account"],
            "qos": plan["scheduler"]["qos"],
            "state": state,
            "exit_code": exit_code,
        },
        "submitted_batch_script_sha256": plan["sbatch"]["sha256"],
    }


def test_task_plan_is_content_addressed_one_gpu_and_explicit_scheduler_cli(tmp_path: Path) -> None:
    authority = _authority(tmp_path)
    task = authority["task_by_id"]["task-0"]

    first = dispatch.build_task_plan(authority, task, 1)
    second = dispatch.build_task_plan(authority, task, 1)

    assert first == second
    assert first["scheduler"] == {
        "job_name": authority["job_names"]["task-0"],
        "account": "ram",
        "qos": "h100_ram_high",
        "nodes": 1,
        "tasks": 1,
        "gpus": 1,
    }
    assert first["command"][:7] == [
        "env",
        "-u",
        "SBATCH_OUTPUT",
        "-u",
        "SBATCH_ERROR",
        "sbatch",
        "--parsable",
    ]
    assert "--qos=h100_ram_high" in first["command"]
    assert "--account=ram" in first["command"]
    script = first["sbatch_content"].decode()
    assert "#SBATCH --nodes=1" in script
    assert "#SBATCH --ntasks=1" in script
    assert "#SBATCH --gres=gpu:1" in script
    assert "#SBATCH --no-requeue" in script
    assert "--task-id task-0" in script
    assert "--attempt 1" in script
    assert Path(first["sbatch"]["path"]).stem == f"task_{first['sbatch']['sha256']}"
    global_intent = dispatch.global_intent(authority, "2026-08-08T00:00:00Z")
    assert global_intent["postrun_authority"] == authority["postrun_authority"]

    changed_authority = copy.deepcopy(authority)
    changed_authority["postrun_authority"]["sha256"] = "4" * 64
    assert dispatch.build_task_plan(changed_authority, task, 1)["comment"] != first["comment"]


def test_selection_requires_explicit_incomplete_tasks_and_caps_each_invocation(tmp_path: Path) -> None:
    authority = _authority(tmp_path)

    selected = dispatch.select_tasks(authority, ["task-0", "task-1"])
    assert [task["task_id"] for task in selected] == ["task-0", "task-1"]
    with pytest.raises(ValueError, match="At most 5"):
        dispatch.select_tasks(authority, [f"task-{index}" for index in range(6)])
    with pytest.raises(ValueError, match="Duplicate"):
        dispatch.select_tasks(authority, ["task-0", "task-0"])

    task = authority["task_by_id"]["task-0"]
    receipt_dir = Path(task["receipt_dir"])
    receipt_dir.mkdir(parents=True)
    receipt_path = receipt_dir / "attempt_0001.json"
    receipt_path.write_bytes(runner.canonical_json_bytes({"status": "succeeded"}))
    receipt_path.chmod(0o444)
    with pytest.raises(ValueError, match="already has a succeeded"):
        dispatch.select_tasks(authority, ["task-0"])


def test_execution_environment_removes_every_ambient_sbatch_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SBATCH_OUTPUT", "/wrong")
    monkeypatch.setenv("SBATCH_QOS", "wrong")
    monkeypatch.setenv("SBATCH_ACCOUNT", "wrong")
    monkeypatch.setenv("KEPT_VALUE", "yes")

    environment = dispatch._execution_environment()

    assert all(not key.startswith("SBATCH_") for key in environment)
    assert environment["KEPT_VALUE"] == "yes"


def test_scheduler_rows_and_live_cap_require_tracked_exact_identity(tmp_path: Path) -> None:
    authority = _authority(tmp_path)
    task = authority["task_by_id"]["task-0"]
    plan = dispatch.build_task_plan(authority, task, 1)
    status = {
        "plans": [plan],
        "receipts": [{"plan": plan, "receipt": {"job_id": 123}}],
    }
    row = f"123|{plan['comment']}|{plan['scheduler']['job_name']}|ram|h100_ram_high|RUNNING\n"
    records = dispatch.parse_scheduler_rows(row, source="squeue")
    snapshot = {"records": records}

    cap = dispatch.enforce_live_cap(authority, status, snapshot, selected_new_count=4)
    assert cap["live_count"] == 1
    assert cap["projected_live_count"] == 5
    with pytest.raises(RuntimeError, match="cap exceeded"):
        dispatch.enforce_live_cap(authority, status, snapshot, selected_new_count=5)

    untracked = {
        "records": [
            {
                **records[0],
                "job_id": 124,
                "comment": f"{dispatch.COMMENT_PREFIX}{'9' * 64}",
            }
        ]
    }
    with pytest.raises(ValueError, match="no immutable dispatch intent"):
        dispatch.enforce_live_cap(authority, {"plans": [], "receipts": []}, untracked, selected_new_count=0)


def test_required_state_root_is_plan_content_addressed() -> None:
    plan = {"plan_id": "7" * 64}
    assert dispatch.required_state_root(plan) == (dispatch.STATE_ROOT_BASE / ("7" * 64)).resolve()
    with pytest.raises(ValueError, match="invalid content address"):
        dispatch.required_state_root({"plan_id": "not-a-hash"})


def test_eval_dispatch_requires_adjacent_matching_postrun_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_root = tmp_path / "runs"
    launch_identity = {"path": "/launch", "size_bytes": 1, "sha256": "1" * 64}
    decision = {
        "eligible_design": "four_arm_smoke_screen",
        "eligible_arm_count": 4,
        "eligible_arm_filenames": [f"arm-{index}" for index in range(4)],
    }
    launch = {
        "inputs": {"run_root": str(run_root.resolve())},
        "preregistered_decision": decision,
    }
    record = {
        "authority": {"initial_launch_authority": {"intent": launch_identity, **decision}},
        "identity": {"path": "/postrun", "size_bytes": 2, "sha256": "2" * 64},
    }
    observed = []

    def validate(path: Path) -> dict[str, object]:
        observed.append(path)
        return record

    monkeypatch.setattr(dispatch.postrun_authority, "validate_authority", validate)

    assert dispatch._postrun_authority(launch, launch_identity) == record
    assert observed == [run_root.resolve() / dispatch.postrun_authority.AUTHORITY_NAME]

    record["authority"]["initial_launch_authority"]["intent"] = {
        **launch_identity,
        "sha256": "3" * 64,
    }
    with pytest.raises(ValueError, match="different RL launch intents"):
        dispatch._postrun_authority(launch, launch_identity)


def test_study_live_cap_counts_other_content_addressed_plans(tmp_path: Path) -> None:
    authority = _authority(tmp_path)
    records = [
        {
            "job_id": index + 100,
            "comment": f"{dispatch.COMMENT_PREFIX}{index:064x}",
            "job_name": f"other-plan-{index}",
            "account": "ram",
            "qos": dispatch.REQUIRED_QOS,
            "state": "RUNNING",
            "source": "squeue",
        }
        for index in range(4)
    ]

    cap = dispatch.enforce_study_live_cap(authority, {"records": records}, selected_new_count=1)
    assert cap["live_count"] == 4
    assert cap["projected_live_count"] == 5
    with pytest.raises(RuntimeError, match="cap exceeded"):
        dispatch.enforce_study_live_cap(authority, {"records": records}, selected_new_count=2)


def test_terminal_scheduler_recovery_advances_missing_runner_receipt_without_success(
    tmp_path: Path,
) -> None:
    authority = _authority(tmp_path)
    task = authority["task_by_id"]["task-0"]
    plan = dispatch.build_task_plan(authority, task, 1)
    paths = {key: Path(value) for key, value in plan["paths"].items()}
    paths["intent"].parent.mkdir(parents=True)
    paths["intent"].write_bytes(runner.canonical_json_bytes({"created_at": "2026-08-08T00:00:00Z"}))
    paths["intent"].chmod(0o444)
    paths["receipt"].write_bytes(runner.canonical_json_bytes({"job_id": 123}))
    paths["receipt"].chmod(0o444)
    submission = {"plan": plan, "receipt": {"job_id": 123}}
    status = {"receipts": [submission]}

    candidates = dispatch._recovery_candidates(authority, status, ["task-0"])
    assert candidates == [(task, submission)]
    terminal = {
        "job_id": "123",
        "array_task_id": None,
        "comment": plan["comment"],
        "job_name": plan["scheduler"]["job_name"],
        "account": "ram",
        "qos": dispatch.REQUIRED_QOS,
        "submitted_batch_script_sha256": plan["sbatch"]["sha256"],
        "terminal_state": "NODE_FAIL",
        "terminal_exit_code": "0:0",
        "submit_time": "2026-08-08T00:00:01",
        "start_time": "2026-08-08T00:00:02",
        "end_time": "2026-08-08T00:03:00",
        "elapsed_seconds": 178,
        "recovered_plan_status": dispatch.recovered_plan_status("NODE_FAIL"),
        "terminal_query": {},
    }
    context, receipt = dispatch.recovered_terminal_receipt(
        authority=authority,
        task=task,
        submission=submission,
        terminal=terminal,
    )
    assert context.attempt == 1
    assert receipt["status"] == "failed"
    assert receipt["terminalization"]["success_synthesis_allowed"] is False
    context.receipt_path.parent.mkdir(parents=True, exist_ok=True)
    context.receipt_path.write_bytes(runner.canonical_json_bytes(receipt))
    context.receipt_path.chmod(0o444)
    assert dispatch.next_attempt(task) == 2
    assert dispatch.build_task_plan(authority, task, 2)["attempt"] == 2
    assert dispatch.recovered_plan_status("COMPLETED") == "failed"


@pytest.mark.parametrize(
    ("recovered", "expected_kind"),
    [(False, "pinned_runner"), (True, "scheduler_recovered_failure")],
)
def test_terminal_provenance_binds_exact_dispatch_submission_and_producer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    recovered: bool,
    expected_kind: str,
) -> None:
    authority, _ = _materialize_terminal_attempt(tmp_path, recovered=recovered)
    state = "NODE_FAIL" if recovered else "FAILED"
    monkeypatch.setattr(
        dispatch,
        "terminal_allocation_evidence",
        lambda job_id, plan: _terminal_allocation(job_id, plan, state=state, exit_code="1:0"),
    )

    summary = dispatch.validate_terminal_receipt_provenance(authority)

    assert summary["terminal_receipt_count"] == 1
    assert summary["runner_produced_receipt_count"] == (0 if recovered else 1)
    assert summary["scheduler_recovered_failure_count"] == (1 if recovered else 0)
    assert summary["task_statuses"] == {"task-0": "failed"}
    assert summary["attempts"][0]["provenance_kind"] == expected_kind
    assert summary["attempts"][0]["job_id"] == "123"


def test_fabricated_canonical_terminal_receipt_with_mixed_job_is_rejected(tmp_path: Path) -> None:
    authority, paths = _materialize_terminal_attempt(tmp_path, recovered=False)
    raw, receipt = runner.read_canonical_json(paths["terminal"])
    assert raw == runner.canonical_json_bytes(receipt)
    receipt["scheduler"]["job_id"] = "999"
    paths["terminal"].chmod(0o644)
    paths["terminal"].write_bytes(runner.canonical_json_bytes(receipt))
    paths["terminal"].chmod(0o444)

    with pytest.raises(ValueError, match="scheduler job_id differs"):
        dispatch.validate_terminal_receipt_provenance(authority)


def test_recovered_terminal_receipt_requires_exact_submission_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority, paths = _materialize_terminal_attempt(tmp_path, recovered=True)
    monkeypatch.setattr(
        dispatch,
        "terminal_allocation_evidence",
        lambda job_id, plan: _terminal_allocation(job_id, plan, state="NODE_FAIL", exit_code="1:0"),
    )
    _, receipt = runner.read_canonical_json(paths["terminal"])
    receipt["terminalization"]["submission_receipt"]["sha256"] = "f" * 64
    paths["terminal"].chmod(0o644)
    paths["terminal"].write_bytes(runner.canonical_json_bytes(receipt))
    paths["terminal"].chmod(0o444)

    with pytest.raises(ValueError, match="terminalization proof differs"):
        dispatch.validate_terminal_receipt_provenance(authority)


def test_terminal_allocation_evidence_is_stable_and_rechecks_submitted_script(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _authority(tmp_path, task_count=1)
    task = authority["task_by_id"]["task-0"]
    plan = dispatch.build_task_plan(authority, task, 1)
    stdout = f"123|{plan['scheduler']['job_name']}|COMPLETED|0:0|ram|h100_ram_high|{plan['comment']}|\n"
    observed = []

    def run(command, **kwargs):
        observed.append((command, kwargs))
        return SimpleNamespace(stdout=stdout)

    monkeypatch.setattr(dispatch.subprocess, "run", run)
    monkeypatch.setattr(dispatch, "_submitted_script_sha256", lambda job_id: plan["sbatch"]["sha256"])
    monkeypatch.setattr(dispatch, "_utc_now", lambda: "2026-08-08T00:02:00Z")

    evidence = dispatch.terminal_allocation_evidence(123, plan)

    assert evidence == _terminal_allocation(123, plan, state="COMPLETED", exit_code="0:0")
    assert observed[0][0] == evidence["sacct_command"]
    assert evidence["queried_at"] == "2026-08-08T00:02:00Z"


def test_terminal_provenance_materializes_live_once_then_validates_offline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority, _ = _materialize_terminal_attempt(tmp_path, recovered=False, succeeded=True)
    live_calls = []

    def capture(job_id, plan):
        live_calls.append(job_id)
        return _terminal_allocation(job_id, plan, state="COMPLETED", exit_code="0:0")

    monkeypatch.setattr(dispatch, "terminal_allocation_evidence", capture)
    monkeypatch.setattr(dispatch, "_utc_now", lambda: "2026-08-08T00:03:00Z")
    payload = dispatch.build_terminal_provenance(authority)
    path = dispatch.terminal_provenance_path(authority)
    dispatch._write_json_once_atomic(path, payload, "terminal provenance")
    assert live_calls == [123]

    def forbidden_live_query(job_id, plan):
        raise AssertionError("offline replay queried the scheduler")

    monkeypatch.setattr(dispatch, "terminal_allocation_evidence", forbidden_live_query)
    validated = dispatch.validate_terminal_provenance_artifact(authority)

    assert validated["identity"] == runner.file_identity(path)
    assert validated["artifact"] == payload
    assert validated["summary"]["task_statuses"] == {"task-0": "succeeded"}
    assert validated["live_scheduler_recheck_count"] == 0


def test_terminal_provenance_refuses_to_freeze_retryable_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority, _ = _materialize_terminal_attempt(tmp_path, recovered=False)

    def forbidden_live_query(job_id, plan):
        raise AssertionError("an incomplete plan queried the scheduler")

    monkeypatch.setattr(dispatch, "terminal_allocation_evidence", forbidden_live_query)

    with pytest.raises(ValueError, match="every planned task's latest attempt to have succeeded"):
        dispatch.build_terminal_provenance(authority)


def test_terminal_provenance_materializer_is_write_once_and_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority, _ = _materialize_terminal_attempt(tmp_path, recovered=False, succeeded=True)
    calls = []

    def capture(job_id, plan):
        calls.append(job_id)
        return _terminal_allocation(job_id, plan, state="COMPLETED", exit_code="0:0")

    monkeypatch.setattr(dispatch, "load_authority", lambda plan_path: authority)
    monkeypatch.setattr(dispatch, "terminal_allocation_evidence", capture)
    monkeypatch.setattr(dispatch, "_utc_now", lambda: "2026-08-08T00:03:00Z")
    args = SimpleNamespace(
        plan=authority["plan_context"].plan_path,
        state_root=authority["state_root"],
        confirm_study_id=dispatch.STUDY_ID,
    )

    first = dispatch.materialize_terminals(args)
    second = dispatch.materialize_terminals(args)

    assert calls == [123]
    assert first["already_materialized"] is False
    assert first["artifact_mutation"] is True
    assert second["already_materialized"] is True
    assert second["artifact_mutation"] is False
    assert first["terminal_provenance"] == second["terminal_provenance"]


def test_terminal_provenance_optional_live_recheck_detects_scheduler_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority, _ = _materialize_terminal_attempt(tmp_path, recovered=False, succeeded=True)
    monkeypatch.setattr(
        dispatch,
        "terminal_allocation_evidence",
        lambda job_id, plan: _terminal_allocation(job_id, plan, state="COMPLETED", exit_code="0:0"),
    )
    monkeypatch.setattr(dispatch, "_utc_now", lambda: "2026-08-08T00:03:00Z")
    payload = dispatch.build_terminal_provenance(authority)
    dispatch._write_json_once_atomic(
        dispatch.terminal_provenance_path(authority),
        payload,
        "terminal provenance",
    )
    monkeypatch.setattr(
        dispatch,
        "terminal_allocation_evidence",
        lambda job_id, plan: _terminal_allocation(job_id, plan, state="FAILED", exit_code="1:0"),
    )

    with pytest.raises(ValueError, match="Live terminal allocation recheck differs"):
        dispatch.validate_terminal_provenance_artifact(authority, live_recheck=True)


def test_succeeded_runner_receipt_rejects_a_still_live_allocation(tmp_path: Path) -> None:
    authority = _authority(tmp_path, task_count=1)
    task = authority["task_by_id"]["task-0"]
    plan = dispatch.build_task_plan(authority, task, 1)
    submission = {"sbatch": plan["sbatch"]}
    scheduler = {
        "job_id": "123",
        "array_task_id": None,
        "comment": plan["comment"],
        "job_name": plan["scheduler"]["job_name"],
        "account": plan["scheduler"]["account"],
        "qos": plan["scheduler"]["qos"],
        "submitted_batch_script_sha256": plan["sbatch"]["sha256"],
    }
    live = _terminal_allocation(123, plan, state="RUNNING", exit_code="0:0")

    with pytest.raises(ValueError, match="is not terminal"):
        dispatch._validate_terminal_allocation_evidence(
            live,
            receipt={"status": "succeeded"},
            scheduler=scheduler,
            plan=plan,
            submission=submission,
            job_id="123",
        )

    completed = _terminal_allocation(123, plan, state="COMPLETED", exit_code="0:0")
    dispatch._validate_terminal_allocation_evidence(
        completed,
        receipt={"status": "succeeded"},
        scheduler=scheduler,
        plan=plan,
        submission=submission,
        job_id="123",
    )
