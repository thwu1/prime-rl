from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import materialize_fixed_clock_sft_gstar_runs as materializer
import materialize_fixed_clock_sft_runs as v2_runs
import pytest
from materialize_fixed_clock_sft_gstar_runs import (
    CONTROL_TMUX_SESSION,
    CONTROL_TMUX_SOCKET,
    CONTROL_TMUX_WINDOW,
    SANITIZED_SBATCH_ENV_VARS,
    SUBMISSION_CONTRACT,
    _finalize_ledger,
    _recover_dispatched_arm,
    build_submission_plan,
    dispatch_intent,
    job_receipt,
    parse_scheduler_job_ids,
    require_control_tmux,
    submission_intent,
    submission_status,
    validate_job_receipt,
    write_json_once,
)


def make_validated(tmp_path: Path, arm_count: int = 2) -> dict:
    launch_root = tmp_path / "launch"
    launch_root.mkdir()
    arms = []
    for index in range(arm_count):
        label = f"arm{index}"
        sbatch = launch_root / f"{label}.sbatch"
        sbatch.write_text("#!/bin/bash\n#SBATCH --gres=gpu:1\n", encoding="utf-8")
        arms.append({"label": label, "sbatch": v2_runs.file_identity(sbatch)})
    manifest = {
        "study_id": materializer.STUDY_ID,
        "launch_root": str(launch_root),
        "arms": arms,
    }
    manifest_path = launch_root / materializer.LAUNCH_MANIFEST_NAME
    materializer.v2_runs.write_json_atomic(manifest_path, manifest)
    return {
        "manifest": manifest,
        "manifest_path": str(manifest_path),
        "manifest_sha256": v2_runs.file_sha256(manifest_path),
    }


def initialize_intent(validated: dict) -> tuple[dict, str, Path, Path, dict]:
    launch_root = Path(validated["manifest"]["launch_root"])
    plan, plan_sha256 = build_submission_plan(validated)
    plan_path = launch_root / materializer.SUBMISSIONS_DIR_NAME / materializer.PLAN_DIR_NAME / f"{plan_sha256}.json"
    write_json_once(plan_path, plan)
    intent_path = launch_root / materializer.SUBMISSIONS_DIR_NAME / materializer.SUBMISSION_INTENT_NAME
    intent = submission_intent(
        plan_path=plan_path,
        plan_sha256=plan_sha256,
        validated=validated,
        control_tmux=SUBMISSION_CONTRACT["control_tmux"],
        created_at_utc="2026-08-07T12:00:00+00:00",
    )
    write_json_once(intent_path, intent)
    return plan, plan_sha256, plan_path, intent_path, intent


def test_submission_plan_uses_sanitized_nonexclusive_argv(tmp_path: Path) -> None:
    validated = make_validated(tmp_path)
    plan, plan_sha256 = build_submission_plan(validated)

    assert len(plan_sha256) == 64
    assert len(plan["arms"]) == 2
    assert plan["arms"][0]["comment"] != plan["arms"][1]["comment"]
    for arm in plan["arms"]:
        command = arm["command"]
        assert command[0] == "env"
        for variable in SANITIZED_SBATCH_ENV_VARS:
            index = command.index(variable)
            assert command[index - 1] == "-u"
        assert "sbatch" in command
        assert "--parsable" in command
        assert f"--comment={arm['comment']}" in command
        assert "--exclusive" not in command
        assert "bash" not in command
        assert "sh" not in command


def test_immutable_receipts_finalize_one_ledger(tmp_path: Path) -> None:
    validated = make_validated(tmp_path)
    plan, plan_sha256, plan_path, intent_path, intent = initialize_intent(validated)
    launch_root = Path(validated["manifest"]["launch_root"])
    for index, arm_plan in enumerate(plan["arms"], start=101):
        dispatch_path = (
            launch_root
            / materializer.SUBMISSIONS_DIR_NAME
            / materializer.DISPATCH_DIR_NAME
            / f"{arm_plan['arm_label']}.json"
        )
        receipt_path = (
            launch_root
            / materializer.SUBMISSIONS_DIR_NAME
            / materializer.RECEIPT_DIR_NAME
            / f"{arm_plan['arm_label']}.json"
        )
        write_json_once(
            dispatch_path,
            dispatch_intent(
                arm_plan=arm_plan,
                plan_path=plan_path,
                plan_sha256=plan_sha256,
                intent_path=intent_path,
                control_tmux=intent["control_tmux"],
            ),
        )
        receipt = job_receipt(
            arm_plan=arm_plan,
            job_id=index,
            plan_path=plan_path,
            plan_sha256=plan_sha256,
            intent_path=intent_path,
            dispatch_path=dispatch_path,
            control_tmux=intent["control_tmux"],
            submission_source="sbatch_stdout",
            sbatch_stdout=str(index),
        )
        write_json_once(receipt_path, receipt)
        validate_job_receipt(
            receipt_path,
            arm_plan=arm_plan,
            plan_path=plan_path,
            plan_sha256=plan_sha256,
            intent_path=intent_path,
            dispatch_path=dispatch_path,
            control_tmux=intent["control_tmux"],
        )

    assert submission_status(validated)["state"] == "receipts_complete_ledger_pending"
    finalized = _finalize_ledger(validated)
    assert finalized["state"] == "submitted"
    assert finalized["submitted"] is True
    assert finalized["job_ids"] == {"arm0": 101, "arm1": 102}
    with pytest.raises(ValueError, match="different immutable submission artifact"):
        write_json_once(intent_path, {"tampered": True})


def test_ambiguous_dispatch_recovers_exactly_one_scheduler_match(tmp_path: Path, monkeypatch) -> None:
    validated = make_validated(tmp_path, arm_count=1)
    plan, plan_sha256, plan_path, intent_path, intent = initialize_intent(validated)
    arm_plan = plan["arms"][0]
    launch_root = Path(validated["manifest"]["launch_root"])
    dispatch_path = (
        launch_root
        / materializer.SUBMISSIONS_DIR_NAME
        / materializer.DISPATCH_DIR_NAME
        / f"{arm_plan['arm_label']}.json"
    )
    receipt_path = (
        launch_root
        / materializer.SUBMISSIONS_DIR_NAME
        / materializer.RECEIPT_DIR_NAME
        / f"{arm_plan['arm_label']}.json"
    )
    write_json_once(
        dispatch_path,
        dispatch_intent(
            arm_plan=arm_plan,
            plan_path=plan_path,
            plan_sha256=plan_sha256,
            intent_path=intent_path,
            control_tmux=intent["control_tmux"],
        ),
    )
    evidence = {
        "squeue_command": ["squeue", "--noheader", "--format=%i|%k"],
        "squeue_stdout_sha256": "a" * 64,
        "squeue_job_ids": [777],
        "sacct_command": [
            "sacct",
            "--noheader",
            "--parsable2",
            "--allocations",
            "--starttime",
            "2026-08-06T12:00:00",
            "--format=JobIDRaw,Comment",
        ],
        "sacct_stdout_sha256": "b" * 64,
        "sacct_job_ids": [777],
        "matched_job_ids": [777],
    }
    monkeypatch.setattr(materializer, "scheduler_matches", lambda *_args, **_kwargs: ({777}, evidence))

    recovered, observed_evidence = _recover_dispatched_arm(
        arm_plan=arm_plan,
        plan_path=plan_path,
        plan_sha256=plan_sha256,
        intent_path=intent_path,
        intent=intent,
        dispatch_path=dispatch_path,
        receipt_path=receipt_path,
    )

    assert recovered is True
    assert observed_evidence == evidence
    assert submission_status(validated)["job_ids"] == {"arm0": 777}
    assert parse_scheduler_job_ids("777|target|\n778|other|\n777.batch|target|\n", comment="target") == {777}


def test_control_tmux_guard_checks_exact_target(monkeypatch) -> None:
    monkeypatch.setenv("TMUX", f"{CONTROL_TMUX_SOCKET},1,0")
    monkeypatch.setenv("TMUX_PANE", "%9")

    def fake_run(command, **kwargs):
        assert command[:3] == ["tmux", "-S", CONTROL_TMUX_SOCKET]
        assert kwargs == {"check": True, "capture_output": True, "text": True}
        return subprocess.CompletedProcess(command, 0, f"{CONTROL_TMUX_SESSION}\t{CONTROL_TMUX_WINDOW}\n", "")

    monkeypatch.setattr(materializer.subprocess, "run", fake_run)
    assert require_control_tmux() == SUBMISSION_CONTRACT["control_tmux"]

    monkeypatch.setenv("TMUX", "/tmp/wrong.sock,1,0")
    with pytest.raises(ValueError, match="socket differs"):
        require_control_tmux()


def test_protected_submit_writes_intents_receipts_and_final_ledger(tmp_path: Path, monkeypatch) -> None:
    validated = make_validated(tmp_path)
    launch_root = Path(validated["manifest"]["launch_root"])
    monkeypatch.setattr(materializer, "validate_launch_manifest", lambda _path: validated)
    monkeypatch.setattr(materializer, "require_control_tmux", lambda: SUBMISSION_CONTRACT["control_tmux"])
    calls = []

    def fake_sbatch(command, **kwargs):
        calls.append(command)
        assert kwargs == {"check": True, "capture_output": True, "text": True}
        return subprocess.CompletedProcess(command, 0, f"{900 + len(calls)}\n", "")

    monkeypatch.setattr(materializer.subprocess, "run", fake_sbatch)
    args = argparse.Namespace(
        launch_root=launch_root,
        dry_run=False,
        confirm_study_id=materializer.STUDY_ID,
    )

    result = materializer.submit(args)
    repeated = materializer.submit(args)

    assert result["status"]["state"] == "submitted"
    assert repeated["status"]["state"] == "submitted"
    assert len(calls) == 2
    for command in calls:
        assert command[0] == "env"
        for variable in materializer.SANITIZED_SBATCH_ENV_VARS:
            index = command.index(variable)
            assert command[index - 1] == "-u"
    submissions = launch_root / materializer.SUBMISSIONS_DIR_NAME
    assert (submissions / materializer.SUBMISSION_INTENT_NAME).is_file()
    assert len(list((submissions / materializer.DISPATCH_DIR_NAME).glob("*.json"))) == 2
    assert len(list((submissions / materializer.RECEIPT_DIR_NAME).glob("*.json"))) == 2
    assert (submissions / materializer.SUBMISSION_LEDGER_NAME).is_file()
