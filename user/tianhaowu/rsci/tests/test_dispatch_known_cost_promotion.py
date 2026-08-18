from __future__ import annotations

import hashlib
from pathlib import Path

import dispatch_known_cost_promotion as dispatcher
import pytest


def _sealed_run(tmp_path: Path) -> dict:
    filename = "b20260809_g_p0075.toml"
    run_dir = tmp_path / filename.removesuffix(".toml")
    run_dir.mkdir()
    source_manifest = run_dir / "source_provenance.json"
    source_manifest.write_text("{}\n", encoding="utf-8")
    sbatch = run_dir / "rl.sbatch"
    sbatch.write_text(
        "#!/bin/bash\n#SBATCH --job-name=rsci-kc1-b09-g-p0075\n#SBATCH --account=ram\n",
        encoding="utf-8",
    )
    return {
        "arm_filename": filename,
        "output_dir": str(run_dir.resolve()),
        "job_name": "rsci-kc1-b09-g-p0075",
        "wandb_name": "known-cost-stage2-test",
        "sbatch": dispatcher.file_identity(sbatch),
        "source_provenance": {"manifest": dispatcher.file_identity(source_manifest)},
        "scientific_config_projection": {
            "projection_sha256": "a" * 64,
            "parsed_resolved_bundle_sha256": "b" * 64,
        },
        "launcher_config_projection": {
            "projection_sha256": "c" * 64,
            "projection": {"slurm": {"account": "ram"}},
        },
    }


def _authority(tmp_path: Path) -> tuple[dict, dict]:
    run = _sealed_run(tmp_path)
    scheduler_inventory = []
    for index, filename in enumerate(dispatcher.promotion._expected_arm_filenames()):
        is_smoke = filename in dispatcher.promotion.SMOKE_ARM_FILENAMES
        scheduler_inventory.append(
            {
                "arm_filename": filename,
                "stage": "initial_smoke" if is_smoke else "stage2_remaining",
                "job_name": (f"rsci-kc1-test-{index:02d}" if filename != run["arm_filename"] else run["job_name"]),
                "account": "ram",
                "qos": dispatcher.REQUIRED_QOS,
            }
        )
    scheduler_by_filename = {item["arm_filename"]: item for item in scheduler_inventory}
    authority = {
        "intent_identity": {
            "path": str((tmp_path / "stage2_submission_intent.json").resolve()),
            "size_bytes": 1,
            "sha256": "d" * 64,
        },
        "promotion_authority_identity": {
            "path": str((tmp_path / "promotion_authority.json").resolve()),
            "size_bytes": 1,
            "sha256": "e" * 64,
        },
        "initial_intent_identity": {
            "path": str((tmp_path / "submission_intent.json").resolve()),
            "size_bytes": 1,
            "sha256": "f" * 64,
        },
        "analysis_identity": {
            "path": str((tmp_path / "analysis.json").resolve()),
            "size_bytes": 1,
            "sha256": "0" * 64,
        },
        "protected_payload_sha256": "1" * 64,
        "eligible_filenames": [run["arm_filename"]],
        "run_by_filename": {run["arm_filename"]: run},
        "scheduler_inventory": scheduler_inventory,
        "scheduler_by_filename": scheduler_by_filename,
        "control_tmux": {
            "socket": "/tmp/control.sock",
            "session": "control",
            "window": "Launcher",
        },
        "run_root": str((tmp_path / "production-run-root").resolve()),
    }
    return authority, run


def test_stage2_selection_forbids_initial_smoke_duplicates_and_large_batches(tmp_path: Path) -> None:
    authority, run = _authority(tmp_path)

    assert dispatcher.select_arms(authority, [run["arm_filename"]]) == [run]
    with pytest.raises(ValueError, match="Initial smoke arms are forbidden"):
        dispatcher.select_arms(authority, [dispatcher.promotion.SMOKE_ARM_FILENAMES[0]])
    with pytest.raises(ValueError, match="Duplicate"):
        dispatcher.select_arms(authority, [run["arm_filename"], run["arm_filename"]])
    with pytest.raises(ValueError, match="At most 5"):
        dispatcher.select_arms(authority, [f"unknown_{index}.toml" for index in range(6)])


def test_stage2_arm_plan_uses_explicit_scheduler_transport_and_strips_sbatch_env(
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
    monkeypatch.setenv("SBATCH_COMMENT", "forbidden")
    monkeypatch.setenv("SBATCH_QOS", "forbidden")
    monkeypatch.setenv("SBATCH_ACCOUNT", "forbidden")
    assert all(not key.startswith("SBATCH_") for key in dispatcher._execution_environment(plan))


def test_live_cap_counts_initial_smoke_jobs_across_all_30_names(tmp_path: Path) -> None:
    authority, _ = _authority(tmp_path)
    smoke = authority["scheduler_by_filename"][dispatcher.promotion.SMOKE_ARM_FILENAMES[0]]
    running = dispatcher.parse_scheduler_rows(
        f"123|stage1-comment|{smoke['job_name']}|ram|h100_ram_high|RUNNING\n",
        source="squeue",
    )

    with pytest.raises(RuntimeError, match="across all 30 names"):
        dispatcher.enforce_study_live_cap(
            authority=authority,
            status={"receipts": {}},
            snapshot={"records": running},
            selected_new_count=5,
        )

    completed = dispatcher.parse_scheduler_rows(
        f"123|stage1-comment|{smoke['job_name']}|ram|h100_ram_high|COMPLETED\n",
        source="sacct",
    )
    result = dispatcher.enforce_study_live_cap(
        authority=authority,
        status={"receipts": {}},
        snapshot={"records": completed},
        selected_new_count=5,
    )
    assert result["queried_job_name_count"] == 30
    assert result["live_count"] == 0
    assert result["projected_live_count"] == 5


def test_stage2_dispatch_intents_are_immutable_without_submitting(tmp_path: Path) -> None:
    authority, run = _authority(tmp_path)
    plan = dispatcher.build_arm_plan(authority, run)
    state_root = tmp_path / "stage2-state"
    global_path = state_root / dispatcher.GLOBAL_INTENT_NAME
    dispatcher._write_json_once_atomic(
        global_path,
        dispatcher.global_intent(
            authority=authority,
            state_root=state_root,
            created_at="2026-08-08T00:00:00Z",
        ),
    )
    batch = dispatcher.batch_intent(
        global_path=global_path,
        arm_plans=[plan],
        created_at="2026-08-08T00:00:01Z",
    )
    batch_path = state_root / "batches" / (hashlib.sha256(dispatcher.canonical_json_bytes(batch)).hexdigest() + ".json")
    dispatcher._write_json_once_atomic(batch_path, batch)
    arm_path, receipt_path = dispatcher._arm_paths(state_root, run["arm_filename"])
    dispatcher._write_json_once_atomic(
        arm_path,
        dispatcher.arm_intent(
            arm_plan=plan,
            global_path=global_path,
            batch_path=batch_path,
            created_at="2026-08-08T00:00:02Z",
        ),
    )

    assert global_path.stat().st_mode & 0o222 == 0
    assert batch_path.stat().st_mode & 0o222 == 0
    assert arm_path.stat().st_mode & 0o222 == 0
    assert dispatcher.validate_global_intent(global_path, authority, state_root)
    assert dispatcher.validate_batch_intent(batch_path, global_path)
    assert dispatcher.validate_arm_intent(arm_path, arm_plan=plan, global_path=global_path)
    assert not receipt_path.exists()
