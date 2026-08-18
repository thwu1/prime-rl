from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import materialize_known_cost_training_completion as completion
import pytest


def _scheduler_contract() -> dict[str, object]:
    return {
        "job_id": 123,
        "comment": "rsci-known-cost-v1-" + "a" * 64,
        "job_name": "rsci-kc1-b08-g-p0125",
        "account": "ram",
        "qos": "h100_ram_high",
        "stdout_path": "/run/job_123.log",
        "stderr_path": "/run/job_123.log",
        "stdout_scheduler_spec": "/run/job_%j.log",
        "stderr_scheduler_spec": "/run/job_%j.log",
    }


def _sacct_row(
    *,
    state: str = "COMPLETED",
    exit_code: str = "0:0",
    expected: dict[str, object] | None = None,
) -> str:
    expected = _scheduler_contract() if expected is None else expected
    return (
        f"{expected['job_id']}|{expected['comment']}|{expected['job_name']}|"
        f"{expected['account']}|{expected['qos']}|{state}|{exit_code}|"
        f"{expected['stdout_scheduler_spec']}|{expected['stderr_scheduler_spec']}\n"
    )


def _terminal_evidence(expected: dict[str, object] | None = None) -> dict[str, object]:
    expected = _scheduler_contract() if expected is None else expected
    stdout = _sacct_row(expected=expected)
    return {
        "queried_at": "2026-08-08T00:00:00Z",
        "command": [
            "sacct",
            "--noheader",
            "--parsable2",
            "--allocations",
            "--jobs",
            "123",
            f"--format={completion.SACCT_FORMAT}",
        ],
        "stdout_sha256": hashlib.sha256(stdout.encode()).hexdigest(),
        "row": completion._parse_terminal_allocation(stdout, expected),
    }


def _context(tmp_path: Path) -> dict[str, object]:
    evidence = tmp_path / "evidence.log"
    evidence.write_text("complete\n", encoding="utf-8")
    inventory = {"evidence": completion.file_identity(evidence)}
    allocation_log = tmp_path / "job_123.log"
    allocation_log.write_text("allocation complete\n", encoding="utf-8")
    expected = {
        **_scheduler_contract(),
        "stdout_path": str(allocation_log.resolve()),
        "stderr_path": str(allocation_log.resolve()),
        "stdout_scheduler_spec": str(tmp_path.resolve() / "job_%j.log"),
        "stderr_scheduler_spec": str(tmp_path.resolve() / "job_%j.log"),
    }
    allocation_identity = completion.file_identity(allocation_log)
    return {
        "launch_authority": {"initial_intent": {"sha256": "b" * 64}},
        "stage1_submission": {
            **expected,
            "submission_receipt": {
                "identity": {"sha256": "c" * 64},
                "canonical_payload_sha256": "d" * 64,
            },
            "allocation_logs": {"stdout": allocation_identity, "stderr": allocation_identity},
            "allocation_log_scheduler_specs": {
                "stdout": expected["stdout_scheduler_spec"],
                "stderr": expected["stderr_scheduler_spec"],
            },
        },
        "run_contract": {
            "arm_filename": "b20260808_g_p0125.toml",
            "run_dir": str(tmp_path.resolve()),
            "eligible_run": {
                "arm_filename": "b20260808_g_p0125.toml",
                "output_dir": str(tmp_path.resolve()),
            },
        },
        "completion_evidence": {
            "trainer_console_log": {"sha256": "e" * 64},
            "orchestrator_console_log": {"sha256": "f" * 64},
            "final_checkpoint_step": 1500,
        },
        "evidence_paths": {"evidence": evidence},
        "replay_toctou": {"before": inventory, "after": inventory},
    }


def test_materialize_success_is_canonical_read_only_and_validates_without_live_scheduler(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    monkeypatch.setattr(completion, "_collect_context", lambda **kwargs: context)
    monkeypatch.setattr(completion, "_query_terminal_allocation", _terminal_evidence)

    validated = completion.materialize_receipt(
        initial_intent_path=tmp_path / "submission_intent.json",
        state_root=tmp_path / "dispatch",
        arm_filename="b20260808_g_p0125.toml",
        run_dir=tmp_path,
    )

    path = tmp_path / completion.RECEIPT_NAME
    assert validated["identity"] == completion.file_identity(path)
    assert path.stat().st_mode & 0o222 == 0
    assert path.read_bytes() == completion.canonical_json_bytes(validated["receipt"])
    assert validated["receipt"]["claim_scope"]["proves_normal_trainer_process_exit"] is False
    assert validated["receipt"]["claim_scope"]["requires_or_claims_wandb_exit_record"] is False
    assert validated["receipt"]["dispatch_stage"] == completion.STAGE1_DISPATCH_STAGE
    assert validated["live_scheduler_recheck"] is None
    assert (
        completion.validate_adjacent_receipt(
            tmp_path,
            arm_filename="b20260808_g_p0125.toml",
        )["identity"]
        == validated["identity"]
    )
    with pytest.raises(ValueError, match="different arm or run"):
        completion.validate_adjacent_receipt(tmp_path, arm_filename="b20260808_t_p0125.toml")


def test_completion_evidence_binds_logs_tomls_ledgers_wandb_streams_and_stable_marker(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    rollouts = tmp_path / "rollouts"
    weights = tmp_path / "weights" / "step_1500"
    trainer_wandb_dir = tmp_path / "wandb" / "offline-run-trainer"
    orchestrator_wandb_dir = tmp_path / "wandb" / "offline-run-orchestrator"
    for directory in (logs, rollouts, weights, trainer_wandb_dir, orchestrator_wandb_dir):
        directory.mkdir(parents=True, exist_ok=True)
    trainer_stream = trainer_wandb_dir / "run-trainer.wandb"
    orchestrator_stream = orchestrator_wandb_dir / "run-orchestrator.wandb"
    trainer_stream.write_bytes(b"trainer-events")
    orchestrator_stream.write_bytes(b"orchestrator-events")
    (rollouts / "train_group_stats.jsonl").write_text("{}\n", encoding="utf-8")
    (rollouts / "train_batch_attempts.jsonl").write_text("{}\n", encoding="utf-8")
    (weights / "STABLE").touch()
    trainer_log = logs / "trainer.log"
    trainer_log.write_text(f"wandb: Run data is saved locally in {trainer_wandb_dir}\n", encoding="utf-8")
    orchestrator_log = logs / "orchestrator.log"
    orchestrator_log.write_text(
        f"wandb: Run data is saved locally in {orchestrator_wandb_dir}\n"
        "Draining pipeline (reached joint stop: steps=1500/1500, finalized_groups=12000/12000; "
        "cancelled 3 in-flight train rollout(s); any in-flight evals will complete)\n"
        "Waiting for stable trainer weights at step 1500 before exit\n"
        "Pipeline drained, exiting main loop\n"
        "Orchestrator step loop done in 1 day\n"
        "Writing final checkpoint\n"
        "Orchestrator finished.\n",
        encoding="utf-8",
    )
    trainer_config = tmp_path / "trainer.toml"
    orchestrator_config = tmp_path / "orchestrator.toml"
    trainer_config.write_text(f'output_dir = "{tmp_path.resolve()}"\n', encoding="utf-8")
    orchestrator_config.write_text(f'output_dir = "{tmp_path.resolve()}"\n', encoding="utf-8")

    evidence, paths = completion._completion_markers(tmp_path, trainer_config, orchestrator_config)

    assert evidence["resolved_training_configs"] == {
        "trainer": completion.file_identity(trainer_config),
        "orchestrator": completion.file_identity(orchestrator_config),
    }
    assert evidence["training_group_ledger"] == completion.file_identity(rollouts / "train_group_stats.jsonl")
    assert evidence["training_batch_attempt_ledger"] == completion.file_identity(
        rollouts / "train_batch_attempts.jsonl"
    )
    assert evidence["local_wandb_streams"] == {
        "trainer": completion.file_identity(trainer_stream),
        "orchestrator": completion.file_identity(orchestrator_stream),
    }
    assert paths["final_checkpoint_stable_marker"] == weights / "STABLE"


@pytest.mark.parametrize(
    ("state", "exit_code", "message"),
    [
        ("RUNNING", "0:0", "not terminal COMPLETED"),
        ("FAILED", "1:0", "not terminal COMPLETED"),
        ("COMPLETED", "1:0", "nonzero ExitCode"),
    ],
)
def test_terminal_allocation_fails_closed_on_nonterminal_or_failed_jobs(
    state: str,
    exit_code: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        completion._parse_terminal_allocation(
            _sacct_row(state=state, exit_code=exit_code),
            _scheduler_contract(),
        )


def test_terminal_allocation_rejects_duplicate_job_steps_and_mismatched_identity() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        completion._parse_terminal_allocation(_sacct_row() + _sacct_row(), _scheduler_contract())
    with pytest.raises(ValueError, match="job-step or invalid"):
        completion._parse_terminal_allocation(
            _sacct_row().replace("123|", "123.batch|", 1),
            _scheduler_contract(),
        )


def test_stage1_allocation_log_contract_rejects_ambiguous_directives_and_stage2(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    sbatch = run_dir / "rl.sbatch"
    sbatch.write_text(
        f"#SBATCH --output={run_dir}/job_%j.log\n"
        f"#SBATCH --output={run_dir}/second_%j.log\n"
        f"#SBATCH --error={run_dir}/job_%j.log\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="2 --output directives"):
        completion._allocation_log_paths(sbatch, run_dir.resolve(), 123)
    with pytest.raises(NotImplementedError, match="Stage-2"):
        completion._require_supported_dispatch_stage(
            {"dispatch_stage": completion.STAGE2_DISPATCH_STAGE},
            supported_dispatch_stages={completion.STAGE1_DISPATCH_STAGE},
        )
    with pytest.raises(NotImplementedError, match="Stage-2"):
        completion.materialize_receipt(
            initial_intent_path=tmp_path / "intent.json",
            state_root=tmp_path / "dispatch",
            arm_filename="b20260808_g_p0125.toml",
            run_dir=run_dir,
            dispatch_stage=completion.STAGE2_DISPATCH_STAGE,
        )


def test_generic_envelope_validator_can_support_a_distinct_future_stage2_adapter(tmp_path: Path) -> None:
    name = "stage2_training_completion_receipt.json"
    path = tmp_path / name
    payload = {
        "schema_version": completion.SCHEMA_VERSION,
        "artifact_type": "rsci_known_cost_stage2_training_completion_receipt",
        "study_id": completion.STUDY_ID,
        "dispatch_stage": completion.STAGE2_DISPATCH_STAGE,
        "inputs": {"run_dir": str(tmp_path.resolve())},
    }
    payload["payload_without_self_hash_sha256"] = completion.canonical_json_sha256(payload)
    path.write_bytes(completion.canonical_json_bytes(payload))
    path.chmod(0o444)

    validated = completion.validate_receipt_envelope(
        path,
        supported_dispatch_stages={completion.STAGE2_DISPATCH_STAGE},
        expected_artifact_type=payload["artifact_type"],
        expected_receipt_name=name,
    )

    assert validated["receipt"] == payload
    with pytest.raises(ValueError, match="differs from the protected"):
        completion._parse_terminal_allocation(
            _sacct_row().replace("|ram|", "|other-account|", 1),
            _scheduler_contract(),
        )


def _write_canonical(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(completion.canonical_json_bytes(payload))


def _stage1_chain_fixture(tmp_path: Path) -> tuple[dict[str, object], dict[str, object], dict[str, Path]]:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    global_path = tmp_path / "dispatch" / "global_submission_intent.json"
    batch_path = tmp_path / "dispatch" / "batches" / f"{'a' * 64}.json"
    arm_path = tmp_path / "dispatch" / "arms" / "b20260808_g_p0125" / "submission_intent.json"
    receipt_path = arm_path.with_name("receipt.json")
    _write_canonical(global_path, {"artifact_type": "global"})
    _write_canonical(batch_path, {"artifact_type": "batch"})
    sbatch_path = run_dir / "rl.sbatch"
    sbatch_path.write_text(
        f"#SBATCH --output={run_dir.resolve()}/job_%j.log\n#SBATCH --error={run_dir.resolve()}/job_%j.log\n",
        encoding="utf-8",
    )
    (run_dir / "job_123.log").write_text("allocation complete\n", encoding="utf-8")
    sbatch = completion.file_identity(sbatch_path)
    source_manifest = {
        "path": str((run_dir / "source_provenance.json").resolve()),
        "size_bytes": 1,
        "sha256": "2" * 64,
    }
    expected = _scheduler_contract()
    plan = {
        "arm_filename": "b20260808_g_p0125.toml",
        "output_dir": str(run_dir.resolve()),
        "sbatch": sbatch,
        "source_provenance": source_manifest,
        "comment": expected["comment"],
        "command": ["sbatch", "rl.sbatch"],
        "scheduler": {
            "job_name": expected["job_name"],
            "account": expected["account"],
            "qos": expected["qos"],
            "sealed_qos_directive": None,
        },
    }
    _write_canonical(arm_path, {"arm_plan": plan, "batch_intent": completion.file_identity(batch_path)})
    receipt = {
        "arm_filename": "b20260808_g_p0125.toml",
        "job_id": expected["job_id"],
        "comment": expected["comment"],
        "command": plan["command"],
        "global_submission_intent": completion.file_identity(global_path),
        "arm_submission_intent": completion.file_identity(arm_path),
        "source": "sbatch_stdout",
    }
    _write_canonical(receipt_path, receipt)
    run = {
        "arm_filename": "b20260808_g_p0125.toml",
        "output_dir": str(run_dir.resolve()),
        "job_name": expected["job_name"],
        "sbatch": sbatch,
        "source_provenance": {"manifest": source_manifest},
    }
    status = {
        "status": {
            "state": "ready",
            "pending": [],
            "receipts": {"b20260808_g_p0125.toml": expected["job_id"]},
        }
    }
    return (
        run,
        status,
        {
            "run_dir": run_dir,
            "global": global_path,
            "batch": batch_path,
            "arm": arm_path,
            "receipt": receipt_path,
        },
    )


def test_stage1_chain_rejects_receipt_or_run_identity_mismatch(tmp_path: Path) -> None:
    run, status, paths = _stage1_chain_fixture(tmp_path)
    valid = completion._validate_stage1_chain(
        run=run,
        run_dir=paths["run_dir"],
        arm_filename="b20260808_g_p0125.toml",
        status_result=status,
        global_path=paths["global"],
        batch_intent_path=paths["batch"],
        arm_intent_path=paths["arm"],
        submission_receipt_path=paths["receipt"],
    )
    assert valid["allocation_logs"] == {
        "stdout": completion.file_identity(paths["run_dir"] / "job_123.log"),
        "stderr": completion.file_identity(paths["run_dir"] / "job_123.log"),
    }
    with pytest.raises(ValueError, match="arm plan and eligible run"):
        completion._validate_stage1_chain(
            run=run,
            run_dir=tmp_path / "different-run",
            arm_filename="b20260808_g_p0125.toml",
            status_result=status,
            global_path=paths["global"],
            batch_intent_path=paths["batch"],
            arm_intent_path=paths["arm"],
            submission_receipt_path=paths["receipt"],
        )

    bad_status = copy.deepcopy(status)
    bad_status["status"]["receipts"]["b20260808_g_p0125.toml"] = 999
    with pytest.raises(ValueError, match="ready protected receipt"):
        completion._validate_stage1_chain(
            run=run,
            run_dir=paths["run_dir"],
            arm_filename="b20260808_g_p0125.toml",
            status_result=bad_status,
            global_path=paths["global"],
            batch_intent_path=paths["batch"],
            arm_intent_path=paths["arm"],
            submission_receipt_path=paths["receipt"],
        )


def test_toctou_identity_change_fails_closed() -> None:
    before = {"log": {"path": "/x", "size_bytes": 1, "sha256": "a" * 64}}
    after = {"log": {"path": "/x", "size_bytes": 2, "sha256": "b" * 64}}

    with pytest.raises(RuntimeError, match="changed during evidence capture"):
        completion._require_unchanged(before, after, "Training completion evidence")


def test_completion_receipt_write_is_idempotent_but_never_replaces(tmp_path: Path) -> None:
    path = tmp_path / completion.RECEIPT_NAME
    payload = {
        "schema_version": completion.SCHEMA_VERSION,
        "artifact_type": completion.ARTIFACT_TYPE,
        "study_id": completion.STUDY_ID,
        "dispatch_stage": completion.STAGE1_DISPATCH_STAGE,
        "run_contract": {"run_dir": str(tmp_path.resolve())},
        "value": 1,
    }
    payload["payload_without_self_hash_sha256"] = completion.canonical_json_sha256(payload)

    identity = completion.write_receipt(path, payload)

    assert completion.write_receipt(path, payload) == identity
    changed = {key: value for key, value in payload.items() if key != "payload_without_self_hash_sha256"}
    changed["value"] = 2
    changed["payload_without_self_hash_sha256"] = completion.canonical_json_sha256(changed)
    with pytest.raises(FileExistsError):
        completion.write_receipt(path, changed)
