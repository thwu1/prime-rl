from __future__ import annotations

from pathlib import Path

import analyze_known_cost_boundary_results as boundary_results
import materialize_known_cost_promoted_eval_authority as promoted
import pytest


def _target(clock_type: str, target: int, value: float) -> dict:
    return {
        "clock_type": clock_type,
        "target": target,
        "value": value,
        "passes": value >= 0.02,
    }


def _decision(first: list[float], second: list[float]) -> dict:
    per_dose = []
    qualifying = []
    for dose, values in zip(promoted.promotion.SMOKE_DOSES, (first, second), strict=True):
        targets = [
            _target(clock, target, value)
            for (clock, target), value in zip(promoted.promotion.REQUIRED_SMOKE_CLOCKS, values, strict=True)
        ]
        passes_all = all(target["passes"] for target in targets)
        if passes_all:
            qualifying.append(dose)
        per_dose.append(
            {
                "nominal_p": dose,
                "targets": targets,
                "passes_all_required_clocks": passes_all,
            }
        )
    return {
        "rule_id": promoted.promotion.RESULT_RULE_ID,
        "constants": {
            "block_seed": 20260808,
            "doses": list(promoted.promotion.SMOKE_DOSES),
            "threshold": 0.02,
            "comparison": "D_A = L_A(persistent_tag_T) - L_A(hidden_group_G)",
            "L_definition": "mean(selected two tags) - mean(unselected four tags), paired by source",
            "operation_band": "op21_40",
            "required_clocks": [
                {"clock_type": clock, "target": target} for clock, target in promoted.promotion.REQUIRED_SMOKE_CLOCKS
            ],
            "require_same_dose_across_all_clocks": True,
            "threshold_uses_unrounded_values": True,
        },
        "per_dose": per_dose,
        "qualifying_doses": qualifying,
        "proceed_to_full_grid": bool(qualifying),
        "applicable": True,
        "decision_status": "proceed_to_full_grid" if qualifying else "stop_after_smoke",
    }


def test_spending_requires_one_same_dose_at_every_clock() -> None:
    same_dose = _decision([0.021, 0.022, 0.023, 0.024], [0.0, 0.0, 0.0, 0.0])
    result = promoted._validate_same_dose_spending({"smoke_spend_decision": same_dose})

    assert result["qualifying_doses"] == [0.0125]
    assert result["cross_dose_clock_aggregation_allowed"] is False

    alternating = _decision([0.021, 0.0, 0.021, 0.0], [0.0, 0.021, 0.0, 0.021])
    with pytest.raises(ValueError, match="did not authorize"):
        promoted._validate_same_dose_spending({"smoke_spend_decision": alternating})


def test_postrun_pin_requires_successor_and_every_reused_consumer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial = {"path": "/initial", "size_bytes": 1, "sha256": "a" * 64}
    record = {
        "authority": {"initial_launch_authority": {"intent": initial}},
        "identity": {"path": str(tmp_path / "postrun.json"), "size_bytes": 1, "sha256": "b" * 64},
    }
    calls = []
    monkeypatch.setattr(promoted.postrun_authority, "validate_authority", lambda _: record)
    monkeypatch.setattr(
        promoted.postrun_authority,
        "validate_recorded_implementation",
        lambda authority, *, name, implementation_path: calls.append((name, implementation_path)),
    )

    assert promoted._validate_postrun_pin(tmp_path / "postrun.json", initial) == record
    assert {name for name, _ in calls} == {
        "promoted_eval_authority",
        "eval_planner",
        "result_analyzer",
        "training_completion_materializer",
    }


def test_promoted_partition_is_append_only_remaining_26() -> None:
    records = []
    for filename in promoted.promotion._expected_arm_filenames():
        stage = "initial_smoke" if filename in promoted.promotion.SMOKE_ARM_FILENAMES else "stage2_remaining"
        records.append(
            {
                "arm_filename": filename,
                "stage": stage,
                "planner_request_run": {"run_id": Path(filename).stem},
            }
        )
    authority = {"combined_run_inventory": {"runs": records}}

    selected = promoted._promoted_runs(authority)

    assert len(selected) == 26
    assert [run["run_id"] for run in selected] == [
        Path(filename).stem for filename in promoted.promotion.remaining_arm_filenames()
    ]

    next(record for record in records if record["arm_filename"] in promoted.promotion.SMOKE_ARM_FILENAMES)["stage"] = (
        "stage2_remaining"
    )
    with pytest.raises(ValueError, match="exact ordered remaining 26"):
        promoted._promoted_runs(authority)


def test_stage2_completion_has_distinct_artifact_and_claim_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(promoted.training_completion, "_validate_frozen_scheduler_evidence", lambda *_: None)
    context = {
        "initial_launch_intent": {"path": "/initial", "size_bytes": 1, "sha256": "a" * 64},
        "postrun_authority": {"path": "/postrun", "size_bytes": 1, "sha256": "f" * 64},
        "promotion_authority": {"path": "/promotion", "size_bytes": 1, "sha256": "b" * 64},
        "stage2_intent": {"path": "/stage2", "size_bytes": 1, "sha256": "c" * 64},
        "historical_stage2_dispatcher": {"path": "/dispatcher", "size_bytes": 1, "sha256": "d" * 64},
        "historical_stage2_status": {"status": {"state": "ready"}},
        "historical_stage2_status_sha256": "e" * 64,
        "stage2_submission": {"job_id": 123},
        "run_contract": {"arm_filename": "b20260809_clean.toml", "run_dir": str(tmp_path)},
        "completion_evidence": {"final_checkpoint_step": 1500},
        "replay_toctou": {"before": {}, "after": {}},
    }
    terminal = {"row": {"job_id": 123}}

    receipt = promoted.build_stage2_completion_receipt(
        promotion_authority_path=tmp_path / "promotion.json",
        stage2_intent_path=tmp_path / "stage2.json",
        arm_filename="b20260809_clean.toml",
        run_dir=tmp_path,
        context=context,
        terminal_allocation=terminal,
        terminal_toctou_before={},
        terminal_toctou_after={},
    )

    assert receipt["artifact_type"] == promoted.STAGE2_COMPLETION_ARTIFACT_TYPE
    assert receipt["artifact_type"] != promoted.training_completion.ARTIFACT_TYPE
    assert promoted.STAGE2_COMPLETION_NAME != promoted.training_completion.RECEIPT_NAME
    assert receipt["dispatch_stage"] == promoted.training_completion.STAGE2_DISPATCH_STAGE
    assert receipt["claim_scope"]["is_distinct_from_stage1_completion_schema"] is True
    assert "stage1_submission" not in receipt


def test_stage2_scheduler_adapter_preserves_sealed_log_specs(tmp_path: Path) -> None:
    stdout = tmp_path / "job_123.out"
    stderr = tmp_path / "job_123.err"
    context = {
        "stage2_submission": {
            "job_id": 123,
            "comment": "sealed",
            "job_name": "stage2-arm",
            "account": "acct",
            "qos": "h100_ram_high",
            "allocation_logs": {
                "stdout": {"path": str(stdout)},
                "stderr": {"path": str(stderr)},
            },
            "allocation_log_scheduler_specs": {
                "stdout": str(tmp_path / "job_%j.out"),
                "stderr": str(tmp_path / "job_%j.err"),
            },
        }
    }

    contract = promoted.training_completion._expected_scheduler_contract(promoted._stage2_scheduler_context(context))

    assert contract["stdout_path"] == str(stdout)
    assert contract["stderr_path"] == str(stderr)
    assert contract["stdout_scheduler_spec"] == str(tmp_path / "job_%j.out")
    assert contract["stderr_scheduler_spec"] == str(tmp_path / "job_%j.err")


def test_promoted_completion_never_falls_back_to_stage1_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = []

    def validate(path: Path) -> dict:
        observed.append(path)
        raise FileNotFoundError(path)

    monkeypatch.setattr(promoted, "validate_stage2_completion_receipt", validate)
    run = {"arm_filename": "b20260809_clean.toml", "output_dir": str(tmp_path)}

    with pytest.raises(FileNotFoundError):
        promoted._validate_training_completion(
            run=run,
            arm_filename=run["arm_filename"],
            dispatch_stage=promoted.training_completion.STAGE2_DISPATCH_STAGE,
            dispatch_record={"job_id": 123},
            pinned_stage1_implementation={},
            pinned_stage2_implementation={},
            initial_intent_identity={},
            postrun_authority_identity={},
            stage2_intent_identity={},
            promotion_authority_identity={},
        )

    assert observed == [tmp_path / promoted.STAGE2_COMPLETION_NAME]
    assert observed[0] != tmp_path / promoted.training_completion.RECEIPT_NAME


def test_stage2_validator_rejects_stage1_artifact_even_at_distinct_path(tmp_path: Path) -> None:
    path = tmp_path / promoted.STAGE2_COMPLETION_NAME
    payload = {
        "schema_version": promoted.SCHEMA_VERSION,
        "artifact_type": promoted.training_completion.ARTIFACT_TYPE,
        "study_id": promoted.STUDY_ID,
        "dispatch_stage": promoted.training_completion.STAGE1_DISPATCH_STAGE,
    }
    path.write_bytes(promoted.canonical_json_bytes(payload))
    path.chmod(0o444)

    with pytest.raises(ValueError, match="wrong schema, artifact, study, or stage"):
        promoted.validate_stage2_completion_receipt(path)


def test_stage2_completion_inputs_reject_state_root_or_extra_fields(tmp_path: Path) -> None:
    context = {
        "promotion_authority": {"path": str(tmp_path / "promotion.json")},
        "stage2_intent": {"path": str(tmp_path / "stage2.json")},
        "run_contract": {"arm_filename": "b20260809_clean.toml", "run_dir": str(tmp_path / "run")},
    }
    inputs = {
        "promotion_authority": str(tmp_path / "promotion.json"),
        "stage2_intent": str(tmp_path / "stage2.json"),
        "stage2_state_root": str(promoted.promotion.REQUIRED_STAGE2_STATE_ROOT.resolve()),
        "arm_filename": "b20260809_clean.toml",
        "run_dir": str(tmp_path / "run"),
    }

    promoted._validate_stage2_completion_inputs(inputs, context)

    with pytest.raises(ValueError, match="inputs differ"):
        promoted._validate_stage2_completion_inputs({**inputs, "stage2_state_root": str(tmp_path)}, context)
    with pytest.raises(ValueError, match="inputs differ"):
        promoted._validate_stage2_completion_inputs({**inputs, "extra": True}, context)


def test_promoted_plan_records_successor_validator_and_existing_task_sources() -> None:
    implementations = promoted._promoted_implementation_identities()

    assert implementations["planner"]["repository_path"] == str(promoted.SCRIPT_REPOSITORY_PATH)
    assert implementations["historical_planner_helpers"]["repository_path"] == promoted.eval_plan.SCRIPT_REPOSITORY_PATH
    assert implementations["evaluator"]["repository_path"] == promoted.eval_plan.EVALUATOR_REPOSITORY_PATH


def test_shared_initialization_must_be_bit_exact() -> None:
    keys = ((21, "source", "raw", 7),)
    untagged_keys = ((21, 0, "source"),)
    tagged = {name: boundary_results.np.zeros((1, 6)) for name in boundary_results.OUTCOMES}
    untagged = {name: boundary_results.np.zeros(1) for name in boundary_results.OUTCOMES}
    left = boundary_results.TaskOutcomes(keys, tagged, untagged_keys, untagged)
    right = boundary_results.TaskOutcomes(
        keys,
        {name: value.copy() for name, value in tagged.items()},
        untagged_keys,
        {name: value.copy() for name, value in untagged.items()},
    )

    assert promoted._same_outcomes(left, right)

    right.tagged[boundary_results.OUTCOMES[0]][0, 0] = 1
    assert not promoted._same_outcomes(left, right)


def _training_partition(run_ids: set[str]) -> dict:
    readouts = []
    for index, run_id in enumerate(sorted(run_ids)):
        factors = {
            "run_id": run_id,
            "block_seed": 20260808 + index,
            "family": "g",
            "dose": 0.0125,
        }
        readouts.extend(
            {**factors, "clock_kind": "optimizer_step", "target": target}
            for target in promoted.eval_plan.DEFAULT_OPTIMIZER_TARGETS
        )
        readouts.extend(
            {**factors, "clock_kind": "raw_groups", "target": target}
            for target in promoted.eval_plan.DEFAULT_RAW_GROUP_TARGETS
        )
    report = {
        "schema_version": promoted.training_readouts.SCHEMA_VERSION,
        "artifact_type": promoted.training_readouts.ARTIFACT_TYPE,
        "analysis_id": promoted.training_readouts.ANALYSIS_ID,
        "study_id": promoted.STUDY_ID,
        "claim_scope": {"summary_type": "descriptive"},
        "availability": {"trainer_stability_per_tag": "unavailable"},
        "provenance": {
            "implementation": {"path": "/consumer", "size_bytes": 1, "sha256": "a" * 64},
            "run_artifacts": {run_id: {"run_id": run_id} for run_id in sorted(run_ids)},
        },
        "arm_clock_readouts": readouts,
    }
    report["payload_without_self_hash_sha256"] = promoted.eval_plan.canonical_json_sha256(report)
    return report


def test_combined_training_readouts_cover_all_30_runs_and_six_clocks() -> None:
    smoke_ids = {f"smoke-{index}" for index in range(4)}
    promoted_ids = {f"promoted-{index}" for index in range(26)}
    smoke = {"training_readouts": _training_partition(smoke_ids)}
    stage2 = {"training_readouts": _training_partition(promoted_ids)}

    combined = promoted._combine_training_readouts(
        smoke_report=smoke,
        promoted_report=stage2,
        smoke_run_ids=smoke_ids,
        promoted_run_ids=promoted_ids,
        smoke_result_identity={"path": "/smoke", "size_bytes": 1, "sha256": "b" * 64},
        promoted_result_identity={"path": "/promoted", "size_bytes": 1, "sha256": "c" * 64},
    )

    assert combined["partition_join"]["combined_run_count"] == 30
    assert combined["partition_join"]["readout_count"] == 180
    assert combined["partition_join"]["all_six_preregistered_clocks_present_per_run"] is True

    missing = _training_partition(promoted_ids)
    missing["arm_clock_readouts"].pop()
    missing["payload_without_self_hash_sha256"] = promoted.eval_plan.canonical_json_sha256(
        {key: value for key, value in missing.items() if key != "payload_without_self_hash_sha256"}
    )
    with pytest.raises(ValueError, match="every exact arm-by-clock"):
        promoted._combine_training_readouts(
            smoke_report=smoke,
            promoted_report={"training_readouts": missing},
            smoke_run_ids=smoke_ids,
            promoted_run_ids=promoted_ids,
            smoke_result_identity={"path": "/smoke"},
            promoted_result_identity={"path": "/promoted"},
        )
