from __future__ import annotations

import copy
import hashlib
import tomllib
from pathlib import Path
from types import SimpleNamespace

import analyze_defect_withdrawal_eval as analysis
import dispatch_defect_withdrawal as dispatch
import materialize_defect_withdrawal_eval as eval_plan
import pytest
import run_defect_withdrawal_eval_task as runner


def _checkpoint(path: Path, content: bytes) -> dict[str, object]:
    path.mkdir(parents=True)
    (path / "STABLE").touch()
    (path / "config.json").write_text("{}\n", encoding="utf-8")
    (path / "model.safetensors").write_bytes(content)
    return eval_plan.directory_identity(path.resolve())


def test_configured_symlinks_are_not_silently_resolved(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_bytes(eval_plan.canonical_json_bytes({"value": 1}))
    target.chmod(0o444)
    link = tmp_path / "link.json"
    link.symlink_to(target.name)

    with pytest.raises(ValueError, match="symlink"):
        eval_plan.file_identity(link)
    allowed = eval_plan.file_identity(link, allow_symlink=True)
    assert allowed["resolved_path"] == str(target.resolve())
    assert allowed["symlink_target"] == target.name
    with pytest.raises(ValueError, match="symlink"):
        eval_plan._read_json(link)
    with pytest.raises(ValueError, match="symlink"):
        eval_plan._write_once(link, target.read_bytes())

    checkpoint = tmp_path / "checkpoint"
    _checkpoint(checkpoint, b"weights")
    checkpoint_link = tmp_path / "checkpoint-link"
    checkpoint_link.symlink_to(checkpoint.name)
    with pytest.raises(ValueError, match="symlink"):
        eval_plan.directory_identity(checkpoint_link)


def test_checkpoint_dedup_keeps_all_logical_occurrences(tmp_path: Path) -> None:
    p05 = _checkpoint(tmp_path / "p05", b"p05")
    p00 = _checkpoint(tmp_path / "p00", b"p00")
    on = _checkpoint(tmp_path / "on", b"on")
    off = _checkpoint(tmp_path / "off", b"off")
    selectors = [
        {
            "readout_id": "p05_source",
            "source": "p05",
            "arm": None,
            "model_step": 4_000,
            "path": p05["resolved_path"],
        },
        {
            "readout_id": "p00_source",
            "source": "p00",
            "arm": None,
            "model_step": 4_000,
            "path": p00["resolved_path"],
        },
        {
            "readout_id": "on_endpoint",
            "source": "p05",
            "arm": "p05_on",
            "model_step": 4_250,
            "path": on["resolved_path"],
        },
        {
            "readout_id": "off_endpoint",
            "source": "p05",
            "arm": "p05_off",
            "model_step": 4_250,
            "path": off["resolved_path"],
        },
    ]
    authority = {"source_models": {"p05": p05, "p00": p00}}
    evidence = {
        "p05_on": {"checkpoints": {"4250": on}},
        "p05_off": {"checkpoints": {"4250": off}},
    }

    models, mapping = eval_plan._deduplicate_models(selectors, evidence, authority)

    assert len(models) == 4
    assert set(mapping) == {selector["readout_id"] for selector in selectors}
    copied_selector = copy.deepcopy(selectors[-1])
    copied_selector["readout_id"] = "off_byte_alias"
    copied_selector["path"] = off["resolved_path"]
    models, mapping = eval_plan._deduplicate_models([*selectors, copied_selector], evidence, authority)
    assert len(models) == 4
    assert mapping["off_endpoint"] == mapping["off_byte_alias"]


def test_task_bundle_is_one_shard_with_fixed_sampling_contract(tmp_path: Path) -> None:
    model_path = tmp_path / "model"
    checkpoint = _checkpoint(model_path, b"weights")
    evaluator = tmp_path / "source" / "figure3_eval.py"
    runner_path = tmp_path / "source" / "runner.py"
    evaluator.parent.mkdir(parents=True)
    evaluator.write_text("# evaluator\n", encoding="utf-8")
    runner_path.write_text("# runner\n", encoding="utf-8")
    tokenizer = tmp_path / "tokenizer"
    tokenizer.mkdir()
    authority = {
        "tokenizer": {"resolved_path": str(tokenizer.resolve())},
        "source_control": {"run_dir": str((tmp_path / "source-run").resolve())},
        "implementations": {
            "evaluator": {"path": str(evaluator.resolve())},
            "runner": {"path": str(runner_path.resolve())},
        },
    }
    model = {
        "model_key": "model_0123456789abcdef",
        "checkpoint": checkpoint,
        "occurrences": [],
    }

    task, artifacts = eval_plan.build_task_bundle(
        model=model,
        task_index=3,
        plan_root=(tmp_path / "plan").resolve(),
        authority=authority,
    )

    assert len(artifacts) == 3
    assert "shards" not in task
    config = tomllib.loads(artifacts[1].content.decode())
    assert config["eval"]["operations"] == list(range(11, 46))
    assert config["eval"]["examples_per_operation"] == 200
    assert config["eval"]["samples_per_prompt"] == 1
    assert config["eval"]["request_seed"] == 20_260_807
    assert config["eval"]["temperature"] == 0.7
    inference = tomllib.loads(artifacts[0].content.decode())
    assert inference["deployment"] == {"type": "single_node", "gpus_per_node": 1}
    assert inference["parallel"] == {"tp": 1, "dp": 1}
    assert b"#SBATCH --gres=gpu:1" in artifacts[2].content
    assert b"DISPATCH_INTENT" in artifacts[2].content


def test_training_terminal_provenance_binds_completion_and_checkpoints(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "run"
    root.mkdir()
    fork_path = root / "withdrawal_seed_manifest.json"
    source_path = root / "source_provenance.json"
    sbatch_path = root / "rl.sbatch"
    submission_path = root / "submission_receipt.json"
    allocation_path = root / "allocation.log"
    ledger_audit_path = root / "training_ledger_audit.json"
    dispatch_authority_path = root / "training_dispatch_authority.json"
    dispatch_intent_path = root / "dispatch_intent.json"
    for path in (fork_path, source_path, submission_path):
        path.write_bytes(eval_plan.canonical_json_bytes({"artifact": path.stem}))
    sbatch_path.write_text("#!/bin/bash\n", encoding="utf-8")
    allocation_path.write_text("COMPLETED 0:0\n", encoding="utf-8")
    ledger_audit_path.write_bytes(eval_plan.canonical_json_bytes({"passed": True}))
    ledger_audit_path.chmod(0o444)
    monkeypatch.setattr(eval_plan.withdrawal_audit, "validate_audit", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(eval_plan, "_validate_training_dispatch_chain", lambda *_args, **_kwargs: None)
    checkpoints = {
        str(step): _checkpoint(root / "weights" / f"step_{step}", str(step).encode()) for step in (4_000, 4_250, 4_375)
    }
    identities = {
        "fork": eval_plan.file_identity(fork_path),
        "source": eval_plan.file_identity(source_path),
        "sbatch": eval_plan.file_identity(sbatch_path),
    }
    dispatch_authority_path.write_bytes(
        eval_plan.canonical_json_bytes({"artifact_type": "rsci_defect_withdrawal_training_dispatch_authority"})
    )
    dispatch_authority_path.chmod(0o444)
    dispatch_intent_path.write_bytes(
        eval_plan.canonical_json_bytes(
            {
                "artifact_type": "rsci_defect_withdrawal_training_dispatch_intent",
                "authority": eval_plan.file_identity(dispatch_authority_path),
                "arm": "p05_on",
                "sbatch": identities["sbatch"],
            }
        )
    )
    dispatch_intent_path.chmod(0o444)
    payload = {
        "schema_version": eval_plan.SCHEMA_VERSION,
        "artifact_type": eval_plan.TRAINING_TERMINAL_ARTIFACT_TYPE,
        "study_id": eval_plan.STUDY_ID,
        "arm": "p05_on",
        "run_root": str(root.resolve()),
        "dispatch_authority": eval_plan.file_identity(dispatch_authority_path),
        "dispatch_intent": eval_plan.file_identity(dispatch_intent_path),
        "fork_manifest": identities["fork"],
        "source_provenance": identities["source"],
        "rl_sbatch": identities["sbatch"],
        "submission_receipt": eval_plan.file_identity(submission_path),
        "allocation_log": eval_plan.file_identity(allocation_path),
        "training_ledger_audit": eval_plan.file_identity(ledger_audit_path),
        "scheduler": {
            "job_id": "123",
            "comment": "a" * 64,
            "job_name": eval_plan.withdrawal_forks.ARMS["p05_on"].job_name,
            "account": "ram",
            "qos": "h100_ram_high",
            "state": "COMPLETED",
            "exit_code": "0:0",
            "restart_count": 0,
            "submitted_batch_script_sha256": identities["sbatch"]["sha256"],
        },
        "checkpoints": checkpoints,
    }
    provenance = eval_plan._with_self_hash(payload)
    eval_plan._write_once(
        root / eval_plan.TRAINING_TERMINAL_NAME,
        eval_plan.canonical_json_bytes(provenance),
    )

    observed = eval_plan._validate_training_terminal_provenance(
        arm="p05_on",
        root=root.resolve(),
        fork_manifest=identities["fork"],
        source_manifest=identities["source"],
        rl_sbatch=identities["sbatch"],
        checkpoints=checkpoints,
    )

    assert observed["record"]["scheduler"]["state"] == "COMPLETED"
    assert observed["record"]["scheduler"]["exit_code"] == "0:0"


def test_receipts_are_contiguous_and_stop_after_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result_root = tmp_path / "results"
    result_root.mkdir()
    for name in eval_plan.SUCCESS_ARTIFACT_NAMES:
        (result_root / name).write_text(f"{name}\n", encoding="utf-8")
    receipt_dir = tmp_path / "receipts" / "task-a"
    task = {
        "task_id": "task-a",
        "job_name": "task-job",
        "sbatch": {"path": "/sbatch", "size_bytes": 1, "sha256": "e" * 64},
        "receipt_dir": str(receipt_dir),
        "result_root": str(result_root),
        "config_bundle_sha256": "a" * 64,
        "checkpoint_inventory_sha256": "b" * 64,
    }
    runner_identity = eval_plan.file_identity(Path(runner.__file__))
    plan = {
        "plan_id": "c" * 64,
        "tasks": [task],
        "implementations": {"runner": runner_identity},
    }
    dispatch_intent = tmp_path / "dispatch_intent.json"
    eval_plan._write_once(
        dispatch_intent,
        eval_plan.canonical_json_bytes({"intent": "test"}),
    )
    first_path, predecessor = runner.attempt_predecessor(task, 1)
    assert predecessor is None
    first = {
        "schema_version": eval_plan.SCHEMA_VERSION,
        "artifact_type": eval_plan.RECEIPT_ARTIFACT_TYPE,
        "plan_id": plan["plan_id"],
        "plan_sha256": "d" * 64,
        "task_id": task["task_id"],
        "attempt": 1,
        "predecessor_receipt_sha256": None,
        "config_bundle_sha256": task["config_bundle_sha256"],
        "checkpoint_inventory_sha256": task["checkpoint_inventory_sha256"],
        "result_root": task["result_root"],
        "dispatch_intent": eval_plan.file_identity(dispatch_intent),
        "runner": runner_identity,
        "status": "failed",
        "started_at": "2026-08-08T00:00:00Z",
        "finished_at": "2026-08-08T00:01:00Z",
        "scheduler": {
            "job_id": "1",
            "array_task_id": None,
            "comment": "f" * 64,
            "job_name": "task-job",
            "account": "ram",
            "qos": "h100_ram_high",
            "submitted_batch_script_sha256": "e" * 64,
        },
        "exit_code": 1,
        "failure": "node loss",
    }
    eval_plan._write_once(first_path, eval_plan.canonical_json_bytes(first))
    second_path, predecessor = runner.attempt_predecessor(task, 2)
    assert predecessor == eval_plan.bytes_sha256(eval_plan.canonical_json_bytes(first))
    second = {
        **first,
        "attempt": 2,
        "predecessor_receipt_sha256": predecessor,
        "status": "succeeded",
        "started_at": "2026-08-08T00:02:00Z",
        "finished_at": "2026-08-08T00:03:00Z",
        "scheduler": {
            "job_id": "2",
            "array_task_id": None,
            "comment": "f" * 64,
            "job_name": "task-job",
            "account": "ram",
            "qos": "h100_ram_high",
            "submitted_batch_script_sha256": "e" * 64,
        },
        "exit_code": 0,
        "artifacts": {name: eval_plan.file_identity(result_root / name) for name in eval_plan.SUCCESS_ARTIFACT_NAMES},
    }
    second.pop("failure")
    eval_plan._write_once(second_path, eval_plan.canonical_json_bytes(second))
    monkeypatch.setattr(eval_plan, "validate_completed_task", lambda _plan, _task: [])
    monkeypatch.setattr(
        dispatch,
        "validate_eval_task_intent",
        lambda *_args, **_kwargs: {"comment": "f" * 64},
    )

    summary = eval_plan.validate_receipt_chain(plan, "d" * 64)

    assert summary == {"receipt_count": 2, "task_statuses": {"task-a": "succeeded"}}
    with pytest.raises(ValueError, match="already succeeded"):
        runner.attempt_predecessor(task, 3)


def test_transition_summary_has_exhaustive_s_a_w_flows() -> None:
    source = {
        (21, 0, "a", 0): "S",
        (21, 1, "b", 0): "A",
        (21, 2, "c", 0): "W",
        (21, 3, "d", 0): "W",
    }
    endpoint = {
        (21, 0, "a", 0): "A",
        (21, 1, "b", 0): "A",
        (21, 2, "c", 0): "A",
        (21, 3, "d", 0): "S",
    }

    summary = analysis.summarize_transition(source, endpoint, (21,))

    assert summary["matrix"]["S"]["A"] == 1
    assert summary["matrix"]["A"]["A"] == 1
    assert summary["matrix"]["W"]["A"] == 1
    assert summary["matrix"]["W"]["S"] == 1
    assert summary["new_a_incidence"] == 0.5
    assert summary["a_loss_incidence"] == 0.0
    assert summary["net_a_change"] == 0.5
    assert summary["a_retention"] == 1.0

    with pytest.raises(ValueError, match="not answer-correct"):
        analysis.category({"perfect": True, "answer_correct": False})


def test_resource_gate_blocks_priorities_and_caps_withdrawal_jobs() -> None:
    empty = {"queried_at": "2026-08-08T00:00:00Z", "command": ["squeue"], "stdout_sha256": "a" * 64, "records": []}
    gate = dispatch.enforce_resource_gate(empty, phase="training", selected_new_count=3)
    assert gate["projected_live_count"] == 3

    priority = copy.deepcopy(empty)
    priority["records"] = [
        {
            "job_id": "1",
            "comment": "",
            "job_name": "rsci-vd-fcsft-arm",
            "account": "ram",
            "qos": "h100_ram_high",
            "state": "RUNNING",
            "source": "squeue",
        }
    ]
    with pytest.raises(RuntimeError, match="resource gate is closed"):
        dispatch.enforce_resource_gate(priority, phase="training", selected_new_count=1)

    saturated = copy.deepcopy(empty)
    saturated["records"] = [
        {
            "job_id": str(index),
            "comment": "",
            "job_name": f"rsci-vdw-eval-{index}",
            "account": "ram",
            "qos": "h100_ram_high",
            "state": "RUNNING",
            "source": "squeue",
        }
        for index in range(1, 6)
    ]
    with pytest.raises(RuntimeError, match="live-job cap"):
        dispatch.enforce_resource_gate(saturated, phase="eval", selected_new_count=1)


def test_runtime_eval_dispatch_binds_intent_and_submission(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    plan_path.write_bytes(eval_plan.canonical_json_bytes({"plan": "test"}))
    plan_path.chmod(0o444)
    sbatch_path = tmp_path / "task.sbatch"
    sbatch_path.write_text("#!/bin/bash\n", encoding="utf-8")
    sbatch = eval_plan.file_identity(sbatch_path)
    plan = {
        "plan_path": str(plan_path),
        "plan_root": str(tmp_path),
        "authority": {"path": "/authority"},
    }
    task = {"task_id": "task-a", "job_name": "rsci-vdw-eval-a", "sbatch": sbatch}
    plan["tasks"] = [task]
    attempt = 1
    state_root = tmp_path / "dispatch"
    global_path = dispatch._global_intent(
        state_root,
        eval_plan.file_identity(plan_path),
        "eval",
    )
    snapshot = {
        "queried_at": "2026-08-08T00:00:00Z",
        "command": ["squeue", "--noheader", f"--format={dispatch.SQUEUE_FORMAT}"],
        "stdout_sha256": "a" * 64,
        "records": [],
    }
    batch_path = dispatch._write_batch_intent(
        state_root,
        authority=eval_plan.file_identity(plan_path),
        global_path=global_path,
        phase="eval",
        selected=[task["task_id"]],
        gate=dispatch.enforce_resource_gate(snapshot, phase="eval", selected_new_count=1),
    )
    intent_path = dispatch._state_paths(
        state_root / "tasks",
        hashlib.sha256(task["task_id"].encode()).hexdigest(),
        attempt,
    )["intent"]
    intent = dispatch._eval_task_intent(
        plan_path,
        plan,
        task,
        attempt,
        global_path,
        batch_path,
        intent_path,
    )
    eval_plan._write_once(intent_path, eval_plan.canonical_json_bytes(intent))
    receipt = {
        "schema_version": 1,
        "artifact_type": dispatch.EVAL_SUBMISSION_ARTIFACT,
        "study_id": eval_plan.STUDY_ID,
        "plan": eval_plan.file_identity(plan_path),
        "task_id": task["task_id"],
        "attempt": attempt,
        "job_id": "123",
        "comment": intent["comment"],
        "sbatch": sbatch,
        "dispatch_intent": eval_plan.file_identity(intent_path),
        "batch_intent": intent["batch_intent"],
        "global_intent": intent["global_intent"],
        "submitted_at": intent["created_at"],
        "submission_source": "sbatch_stdout",
        "sbatch_stdout": "123",
    }
    eval_plan._write_once(
        intent_path.with_name("submission_receipt.json"),
        eval_plan.canonical_json_bytes(receipt),
    )

    runtime = dispatch.validate_runtime_eval_dispatch(
        intent_path,
        plan=plan,
        task=task,
        attempt=attempt,
        job_id="123",
    )

    assert runtime["scheduler"]["comment"] == intent["comment"]
    assert runtime["scheduler"]["submitted_batch_script_sha256"] == sbatch["sha256"]


def test_terminal_allocation_requires_exact_scheduler_and_script(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdout = (
        "123|" + "a" * 64 + "|job|ram|h100_ram_high|COMPLETED|0:0|"
        "2026-08-08T00:00:00|2026-08-08T00:01:00|2026-08-08T00:02:00|60|0\n"
    )
    monkeypatch.setattr(
        dispatch.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=stdout, stderr="", returncode=0),
    )
    monkeypatch.setattr(dispatch, "_submitted_script_sha256", lambda _job_id: "b" * 64)
    expected = {
        "job_id": "123",
        "comment": "a" * 64,
        "job_name": "job",
        "account": "ram",
        "qos": "h100_ram_high",
        "submitted_batch_script_sha256": "b" * 64,
    }

    evidence = dispatch.terminal_allocation("123", expected=expected)

    assert evidence["record"]["state"] == "COMPLETED"
    assert evidence["record"]["exit_code"] == "0:0"
    assert evidence["record"]["elapsed_seconds"] == 60
    assert evidence["record"]["restart_count"] == 0


def test_live_scheduler_snapshot_uses_numeric_allocation_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdout = (
        "9503553|comment|array-job|ram|h100_ram_high|PENDING|"
        "2026-08-08T00:00:00\n"
    )
    observed_command: list[str] = []

    def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        observed_command.extend(command)
        return SimpleNamespace(stdout=stdout, stderr="", returncode=0)

    monkeypatch.setattr(dispatch.subprocess, "run", fake_run)

    snapshot = dispatch.live_scheduler_snapshot()

    assert f"--format={dispatch.SQUEUE_FORMAT}" in observed_command
    assert dispatch.SQUEUE_FORMAT.startswith("%A|")
    assert snapshot["records"][0]["job_id"] == "9503553"


def test_submission_mode_rejects_mismatched_direct_and_reconciled_claims() -> None:
    dispatch._validate_submission_mode(
        source="sbatch_stdout",
        stdout="123;cluster",
        job_id="123",
        removed_sbatch_variables=["SBATCH_ACCOUNT", "SBATCH_QOS"],
    )
    dispatch._validate_submission_mode(
        source="scheduler_reconciliation",
        stdout=None,
        job_id="123",
        removed_sbatch_variables=[],
    )
    with pytest.raises(ValueError, match="stdout"):
        dispatch._validate_submission_mode(
            source="sbatch_stdout",
            stdout="124",
            job_id="123",
        )
    with pytest.raises(ValueError, match="cannot claim"):
        dispatch._validate_submission_mode(
            source="scheduler_reconciliation",
            stdout="123",
            job_id="123",
        )
    with pytest.raises(ValueError, match="SBATCH"):
        dispatch._validate_submission_mode(
            source="sbatch_stdout",
            stdout="123",
            job_id="123",
            removed_sbatch_variables=["PATH"],
        )


def test_terminal_allocation_parser_exposes_and_requires_restart_count() -> None:
    prefix = (
        "123|" + "a" * 64 + "|job|ram|h100_ram_high|COMPLETED|0:0|"
        "2026-08-08T00:00:00|2026-08-08T00:01:00|2026-08-08T00:02:00|60|"
    )

    assert dispatch._parse_terminal_allocation_stdout(prefix + "1\n", job_id="123")["restart_count"] == 1
    with pytest.raises(ValueError):
        dispatch._parse_terminal_allocation_stdout(prefix + "\n", job_id="123")


def test_training_reconciliation_rejects_path_like_arm_before_scheduler_access() -> None:
    with pytest.raises(ValueError, match="exact arm names"):
        dispatch.reconcile_training(
            Path("/does/not/matter"),
            ["../p05_on"],
            confirm_study_id=eval_plan.STUDY_ID,
        )


def test_training_submission_validator_rejects_rehashed_source_stdout_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_root = tmp_path / "state"
    paths = dispatch._state_paths(state_root, "p05_on")
    eval_plan._write_once(paths["intent"], eval_plan.canonical_json_bytes({"intent": True}))
    sbatch_path = tmp_path / "rl.sbatch"
    sbatch_path.write_text("#!/bin/bash\n", encoding="utf-8")
    sbatch = eval_plan.file_identity(sbatch_path)
    arm = {
        "arm": "p05_on",
        "job_name": "rsci-vd-withdraw-p05-on",
        "sbatch": sbatch,
    }
    authority = {"state_root": str(state_root)}
    intent = {
        "created_at": "2026-08-08T00:00:00Z",
        "comment": "a" * 64,
    }
    monkeypatch.setattr(dispatch, "_validate_training_intent", lambda *_args, **_kwargs: intent)
    payload = {
        "schema_version": dispatch.SCHEMA_VERSION,
        "artifact_type": dispatch.TRAINING_SUBMISSION_ARTIFACT,
        "study_id": dispatch.STUDY_ID,
        "arm": "p05_on",
        "dispatch_intent": eval_plan.file_identity(paths["intent"]),
        "job_id": "123",
        "comment": intent["comment"],
        "sbatch": sbatch,
        "submitted_at": intent["created_at"],
        "source": "scheduler_reconciliation",
        "sbatch_stdout": "123",
        "removed_sbatch_environment_variables": [],
        "scheduler_verification": {
            "command": ["scontrol", "show", "job", "123", "--oneliner"],
            "stdout_sha256": "b" * 64,
            "submitted_batch_script_sha256": sbatch["sha256"],
            "record": {
                "job_id": "123",
                "comment": intent["comment"],
                "job_name": arm["job_name"],
                "account": "ram",
                "qos": "h100_ram_high",
            },
        },
    }
    receipt = dispatch._self_hashed(payload)
    eval_plan._write_once(paths["receipt"], eval_plan.canonical_json_bytes(receipt))

    with pytest.raises(ValueError, match="cannot claim"):
        dispatch._validate_training_submission(
            paths["receipt"],
            authority_path=tmp_path / "authority.json",
            authority=authority,
            arm=arm,
        )


def test_control_tmux_rejects_environment_spoof_from_another_tty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TMUX", f"{dispatch.CONTROL_TMUX['socket']},1,0")
    monkeypatch.setenv("TMUX_PANE", "%1")
    monkeypatch.setattr(dispatch.os, "ttyname", lambda _fd: "/dev/pts/10")
    monkeypatch.setattr(
        dispatch.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout=(
                f"{dispatch.CONTROL_TMUX['session']}\t"
                f"{dispatch.CONTROL_TMUX['window']}\t/dev/pts/11\n"
            ),
            stderr="",
            returncode=0,
        ),
    )

    with pytest.raises(ValueError, match="process TTY"):
        dispatch.require_control_tmux()
