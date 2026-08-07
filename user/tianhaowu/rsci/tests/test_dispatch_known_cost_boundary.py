from __future__ import annotations

import hashlib
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import dispatch_known_cost_boundary as dispatcher
import pytest


def _sealed_run(
    tmp_path: Path,
    filename: str = "b20260808_g_p0125.toml",
    *,
    sealed_qos: str | None = None,
    projected_qos: str | None = None,
) -> dict:
    run_dir = tmp_path / filename.removesuffix(".toml")
    run_dir.mkdir()
    source_manifest = run_dir / "source_provenance.json"
    source_manifest.write_text("{}\n", encoding="utf-8")
    sbatch = run_dir / "rl.sbatch"
    directives = [
        "#!/bin/bash",
        "#SBATCH --job-name=rsci-kc1-b08-g-p0125",
        "#SBATCH --account=ram",
    ]
    if sealed_qos is not None:
        directives.append(f"#SBATCH --qos={sealed_qos}")
    sbatch.write_text("\n".join((*directives, "")), encoding="utf-8")
    slurm_projection = {"account": "ram"}
    if projected_qos is not None:
        slurm_projection["qos"] = projected_qos
    return {
        "arm_filename": filename,
        "output_dir": str(run_dir.resolve()),
        "job_name": "rsci-kc1-b08-g-p0125",
        "wandb_name": "known-cost-test",
        "sbatch": dispatcher.file_identity(sbatch),
        "source_provenance": {"manifest": dispatcher.file_identity(source_manifest)},
        "scientific_config_projection": {
            "projection_sha256": "a" * 64,
            "parsed_resolved_bundle_sha256": "b" * 64,
        },
        "launcher_config_projection": {
            "projection_sha256": "c" * 64,
            "projection": {
                "slurm": slurm_projection,
            },
        },
    }


def _authority(tmp_path: Path) -> tuple[dict, dict]:
    run = _sealed_run(tmp_path)
    filename = run["arm_filename"]
    excluded = "b20260808_t_p0075.toml"
    payload = {"study_id": dispatcher.STUDY_ID}
    authority = {
        "intent": {"preregistered_decision": {"eligible_design": "four_arm_smoke_screen"}},
        "intent_identity": {
            "path": str((tmp_path / "submission_intent.json").resolve()),
            "size_bytes": 1,
            "sha256": "d" * 64,
        },
        "protected_payload": payload,
        "protected_payload_sha256": dispatcher.canonical_json_sha256(payload),
        "eligible_filenames": [filename],
        "run_by_filename": {filename: run},
        "payload_by_filename": {filename: {}},
        "inventory_by_filename": {
            filename: {"decision_status": "eligible"},
            excluded: {"decision_status": "excluded"},
        },
        "control_tmux": {"socket": "/tmp/control.sock", "session": "control", "window": "Launcher"},
        "run_root": str((tmp_path / "production-run-root").resolve()),
    }
    return authority, run


def test_subset_selection_rejects_excluded_duplicates_and_more_than_five(tmp_path: Path) -> None:
    authority, run = _authority(tmp_path)

    assert dispatcher.select_arms(authority, [run["arm_filename"]]) == [run]
    with pytest.raises(ValueError, match="excluded"):
        dispatcher.select_arms(authority, ["b20260808_t_p0075.toml"])
    with pytest.raises(ValueError, match="Duplicate"):
        dispatcher.select_arms(authority, [run["arm_filename"], run["arm_filename"]])
    with pytest.raises(ValueError, match="At most 5"):
        dispatcher.select_arms(authority, [f"arm_{index}.toml" for index in range(6)])


def test_state_root_must_match_the_single_authority_path(tmp_path: Path) -> None:
    authority, _ = _authority(tmp_path)

    with pytest.raises(ValueError, match="exactly match the launch authority"):
        dispatcher.validate_state_root((tmp_path / "alternate-state").resolve(), authority)

    assert (
        dispatcher.validate_state_root(dispatcher.REQUIRED_DISPATCH_STATE_ROOT, authority)
        == dispatcher.REQUIRED_DISPATCH_STATE_ROOT
    )


def test_arm_plan_uses_exact_command_and_content_addressed_comment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority, run = _authority(tmp_path)

    plan = dispatcher.build_arm_plan(authority, run)

    assert plan["command"] == [
        "env",
        "-u",
        "SBATCH_OUTPUT",
        "-u",
        "SBATCH_ERROR",
        "sbatch",
        "--parsable",
        f"--comment={plan['comment']}",
        "--qos=h100_ram_high",
        "--account=ram",
        run["sbatch"]["path"],
    ]
    assert dispatcher.COMMENT_RE.fullmatch(plan["comment"])
    assert plan["submission_environment"]["set"] == {}
    assert plan["scheduler"]["sealed_qos_directive"] is None
    assert plan["submission_environment"]["scheduler_overrides_are_explicit_cli_arguments"] is True
    monkeypatch.setenv("SBATCH_COMMENT", "ambient-is-forbidden")
    monkeypatch.setenv("SBATCH_QOS", "ambient-is-forbidden")
    assert all(not key.startswith("SBATCH_") for key in dispatcher._execution_environment(plan))
    changed = {**authority, "protected_payload_sha256": "e" * 64}
    assert dispatcher.submission_comment(changed, run) != plan["comment"]


def test_scheduler_contract_rejects_conflicting_explicit_qos(tmp_path: Path) -> None:
    run = _sealed_run(tmp_path, sealed_qos="some_other_qos")

    with pytest.raises(ValueError, match="conflicts with the required QoS"):
        dispatcher.scheduler_contract(run)


def test_prelaunch_status_is_not_treated_as_started(tmp_path: Path) -> None:
    run = _sealed_run(tmp_path)
    output_dir = Path(run["output_dir"])
    (output_dir / "STATUS.md").write_text("sealed and not submitted\n", encoding="utf-8")

    assert dispatcher._started_artifacts(run) == []

    (output_dir / "job_123.log").write_text("queued\n", encoding="utf-8")
    assert dispatcher._started_artifacts(run) == ["job_123.log"]


def test_scheduler_matching_is_exact_and_merges_squeue_with_sacct(tmp_path: Path) -> None:
    authority, run = _authority(tmp_path)
    plan = dispatcher.build_arm_plan(authority, run)
    output = (
        f"123|{plan['comment']}|{plan['scheduler']['job_name']}|ram|h100_ram_high|RUNNING\n"
        "124|different|rsci-kc1-b08-g-p0125|ram|h100_ram_high|PENDING\n"
    )
    records = dispatcher.parse_scheduler_rows(output, source="squeue")
    records.extend(dispatcher.parse_scheduler_rows(output.splitlines()[0] + "\n", source="sacct"))
    snapshot = {"records": records}

    exact = dispatcher.matching_scheduler_jobs(snapshot, plan, exact_comment_only=True)
    already_started = dispatcher.matching_scheduler_jobs(snapshot, plan, exact_comment_only=False)

    assert list(exact) == [123]
    assert exact[123]["sources"] == ["sacct", "squeue"]
    assert sorted(already_started) == [123, 124]
    dispatcher._validate_scheduler_match(exact[123], plan)


def test_scheduler_parser_fails_closed_on_delimiters_and_nonstandard_job_ids() -> None:
    with pytest.raises(ValueError, match="Malformed squeue scheduler row"):
        dispatcher.parse_scheduler_rows(
            "123|comment|with-pipe|eligible-name|ram|h100_ram_high|RUNNING\n",
            source="squeue",
        )
    with pytest.raises(ValueError, match="Unexpected sacct scheduler job ID"):
        dispatcher.parse_scheduler_rows(
            "123_4|comment|eligible-name|ram|h100_ram_high|RUNNING\n",
            source="sacct",
        )


def test_scheduler_snapshot_filters_exact_job_names_without_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(dispatcher.subprocess, "run", run)

    snapshot = dispatcher.scheduler_snapshot(
        start_time=datetime(2026, 8, 8, tzinfo=UTC),
        job_names=["rsci-kc1-b08-t-p0125", "rsci-kc1-b08-g-p0125"],
    )

    name_filter = "rsci-kc1-b08-g-p0125,rsci-kc1-b08-t-p0125"
    assert commands[0][1:4] == ["--noheader", "--name", name_filter]
    assert commands[1][1:6] == ["--noheader", "--parsable2", "--allocations", "--name", name_filter]
    assert all("--user" not in command for command in commands)
    assert snapshot["records"] == []


def test_study_live_cap_counts_exact_comments_and_terminal_state(tmp_path: Path) -> None:
    authority, run = _authority(tmp_path)
    plan = dispatcher.build_arm_plan(authority, run)
    status = {"receipts": {}}
    running = dispatcher.parse_scheduler_rows(
        f"123|{plan['comment']}|{plan['scheduler']['job_name']}|ram|h100_ram_high|RUNNING\n",
        source="squeue",
    )

    with pytest.raises(RuntimeError, match="5 selected > 5"):
        dispatcher.enforce_study_live_cap(
            authority=authority,
            status=status,
            snapshot={"records": running},
            selected_new_count=5,
        )

    completed = dispatcher.parse_scheduler_rows(
        f"123|{plan['comment']}|{plan['scheduler']['job_name']}|ram|h100_ram_high|COMPLETED\n",
        source="sacct",
    )
    result = dispatcher.enforce_study_live_cap(
        authority=authority,
        status=status,
        snapshot={"records": completed},
        selected_new_count=5,
    )
    assert result["projected_live_count"] == 5
    assert result["live_jobs"] == []


def test_study_live_cap_merges_empty_sacct_comment_with_squeue(tmp_path: Path) -> None:
    authority, run = _authority(tmp_path)
    plan = dispatcher.build_arm_plan(authority, run)
    squeue = dispatcher.parse_scheduler_rows(
        f"123|{plan['comment']}|{plan['scheduler']['job_name']}|ram|h100_ram_high|PENDING\n",
        source="squeue",
    )
    sacct = dispatcher.parse_scheduler_rows(
        f"123||{plan['scheduler']['job_name']}|ram|h100_ram_high|PENDING\n",
        source="sacct",
    )

    result = dispatcher.enforce_study_live_cap(
        authority=authority,
        status={"receipts": {run["arm_filename"]: 123}},
        snapshot={"records": [*squeue, *sacct]},
        selected_new_count=0,
    )

    assert result["live_count"] == 1
    assert result["live_jobs"][0]["sources"] == ["sacct", "squeue"]


def test_study_live_cap_rejects_live_eligible_name_without_exact_comment(tmp_path: Path) -> None:
    authority, run = _authority(tmp_path)
    plan = dispatcher.build_arm_plan(authority, run)
    running = dispatcher.parse_scheduler_rows(
        f"321||{plan['scheduler']['job_name']}|ram|h100_ram_high|RUNNING\n",
        source="squeue",
    )

    with pytest.raises(ValueError, match="exact content-addressed comment"):
        dispatcher.enforce_study_live_cap(
            authority=authority,
            status={"receipts": {}},
            snapshot={"records": running},
            selected_new_count=1,
        )

    completed = dispatcher.parse_scheduler_rows(
        f"321||{plan['scheduler']['job_name']}|ram|h100_ram_high|COMPLETED\n",
        source="sacct",
    )
    result = dispatcher.enforce_study_live_cap(
        authority=authority,
        status={"receipts": {}},
        snapshot={"records": completed},
        selected_new_count=1,
    )
    assert result["live_count"] == 0


def test_ambiguous_sbatch_leaves_intent_without_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority, run = _authority(tmp_path)
    plan = dispatcher.build_arm_plan(authority, run)
    state_root = (tmp_path / "dispatch-state").resolve()
    state_root.mkdir()
    global_path = state_root / dispatcher.GLOBAL_INTENT_NAME
    dispatcher._write_json_once_atomic(
        global_path,
        dispatcher.global_intent(authority=authority, state_root=state_root, created_at="2026-08-08T00:00:00Z"),
    )
    assert global_path.stat().st_mode & 0o222 == 0
    batch = dispatcher.batch_intent(
        global_path=global_path,
        arm_plans=[plan],
        created_at="2026-08-08T00:00:01Z",
    )
    batch_bytes = dispatcher.canonical_json_bytes(batch)
    batch_path = state_root / "batches" / f"{hashlib.sha256(batch_bytes).hexdigest()}.json"
    dispatcher._write_json_once_atomic(batch_path, batch)
    assert batch_path.stat().st_mode & 0o222 == 0
    monkeypatch.setattr(
        dispatcher.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, stdout="", stderr="rejected"),
    )

    with pytest.raises(RuntimeError, match="Ambiguous sbatch outcome"):
        dispatcher._submit_one(
            arm_plan=plan,
            global_path=global_path,
            batch_path=batch_path,
            state_root=state_root,
        )

    intent_path, receipt_path = dispatcher._arm_paths(state_root, run["arm_filename"])
    assert intent_path.is_file()
    assert intent_path.stat().st_mode & 0o222 == 0
    assert not receipt_path.exists()
    status = dispatcher.state_status(authority, state_root)
    assert status["state"] == "ambiguous_submission_pending_reconciliation"
    assert status["pending"] == [run["arm_filename"]]

    intent_path.chmod(0o644)
    with pytest.raises(ValueError, match="Per-arm dispatch intent must be read-only"):
        dispatcher.validate_arm_intent(intent_path, arm_plan=plan, global_path=global_path)
    intent_path.chmod(0o444)
    batch_path.chmod(0o644)
    with pytest.raises(ValueError, match="Batch dispatch intent must be read-only"):
        dispatcher.validate_batch_intent(batch_path, global_path)
    batch_path.chmod(0o444)
    global_path.chmod(0o644)
    with pytest.raises(ValueError, match="Global dispatch intent must be read-only"):
        dispatcher.validate_global_intent(global_path, authority, state_root)


def test_sbatch_mutation_during_submission_leaves_no_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority, run = _authority(tmp_path)
    plan = dispatcher.build_arm_plan(authority, run)
    state_root = (tmp_path / "dispatch-state").resolve()
    state_root.mkdir()
    global_path = state_root / dispatcher.GLOBAL_INTENT_NAME
    dispatcher._write_json_once_atomic(
        global_path,
        dispatcher.global_intent(authority=authority, state_root=state_root, created_at="2026-08-08T00:00:00Z"),
    )
    batch = dispatcher.batch_intent(
        global_path=global_path,
        arm_plans=[plan],
        created_at="2026-08-08T00:00:01Z",
    )
    batch_bytes = dispatcher.canonical_json_bytes(batch)
    batch_path = state_root / "batches" / f"{hashlib.sha256(batch_bytes).hexdigest()}.json"
    dispatcher._write_json_once_atomic(batch_path, batch)

    def mutate_sbatch(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        Path(plan["sbatch"]["path"]).write_text("changed during sbatch\n", encoding="utf-8")
        return subprocess.CompletedProcess(plan["command"], 0, stdout="123", stderr="")

    monkeypatch.setattr(dispatcher.subprocess, "run", mutate_sbatch)

    with pytest.raises(RuntimeError, match="Ambiguous sbatch outcome"):
        dispatcher._submit_one(
            arm_plan=plan,
            global_path=global_path,
            batch_path=batch_path,
            state_root=state_root,
        )

    intent_path, receipt_path = dispatcher._arm_paths(state_root, run["arm_filename"])
    assert intent_path.is_file()
    assert not receipt_path.exists()


def test_receipt_evidence_must_prove_exact_comment_account_and_qos(tmp_path: Path) -> None:
    authority, run = _authority(tmp_path)
    plan = dispatcher.build_arm_plan(authority, run)
    evidence = {
        "command": ["scontrol", "show", "job", "123", "--oneliner"],
        "stdout_sha256": "f" * 64,
        "record": {
            "job_id": 123,
            "comment": plan["comment"],
            "job_name": plan["scheduler"]["job_name"],
            "account": "ram",
            "qos": "h100_ram_high",
        },
    }
    global_path = tmp_path / "global.json"
    global_path.write_text("{}\n", encoding="utf-8")
    arm_path = tmp_path / "arm.json"
    arm_path.write_text("{}\n", encoding="utf-8")

    receipt = dispatcher.submission_receipt(
        arm_plan=plan,
        global_path=global_path,
        arm_intent_path=arm_path,
        job_id=123,
        source="sbatch_stdout",
        sbatch_stdout="123",
        scheduler_evidence=evidence,
    )
    assert receipt["job_id"] == 123
    receipt_path = tmp_path / "receipt.json"
    dispatcher._write_json_once_atomic(receipt_path, receipt)
    assert receipt_path.stat().st_mode & 0o222 == 0
    assert (
        dispatcher.validate_receipt(
            receipt_path,
            arm_plan=plan,
            global_path=global_path,
            arm_intent_path=arm_path,
        )
        == receipt
    )
    receipt_path.chmod(0o644)
    with pytest.raises(ValueError, match="Submission receipt must be read-only"):
        dispatcher.validate_receipt(
            receipt_path,
            arm_plan=plan,
            global_path=global_path,
            arm_intent_path=arm_path,
        )

    bad = {**evidence, "record": {**evidence["record"], "comment": "wrong"}}
    with pytest.raises(ValueError, match="exact content-addressed comment"):
        dispatcher.submission_receipt(
            arm_plan=plan,
            global_path=global_path,
            arm_intent_path=arm_path,
            job_id=123,
            source="sbatch_stdout",
            sbatch_stdout="123",
            scheduler_evidence=bad,
        )
