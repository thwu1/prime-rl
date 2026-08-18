from __future__ import annotations

import json
from pathlib import Path

import analyze_known_cost_training_readouts as training
import pytest
from wandb.proto import wandb_internal_pb2
from wandb.sdk.internal import datastore


def _trainer_row(step: int, value: float = 0.1) -> dict[str, float | int]:
    return {"step": step, **{key: value for key in training.TRAINER_METRIC_KEYS}}


def _group(tag: int, *, stale: bool = False) -> dict[str, object]:
    scored = not stale
    return {
        "neutral_tag_index": tag,
        "reward_scored": scored,
        "unscored_cause": "off_policy_cancellation" if stale else None,
        "errored_count": 128 if stale else 0,
        "defect_gate_open": tag in {0, 1},
        "V_valid_count": 0 if stale else 128,
        "S_strict_positive_count": 0 if stale else 32,
        "C_candidate_count": 0 if stale else 64,
        "K_effective_eligible_count": 0 if stale else 64,
        "H_behavior_trigger_count": 0 if stale else 8,
        "selected_extra_positive_count": 0 if stale else 8,
        "behavior_tax_applied_total": 0.0 if stale else 1.92,
        "selected_net_behavior_reward_total": 0.0 if stale else 6.08,
        "proxy_reward_histogram": {} if stale else {"-0.03": 64, "0.0": 24, "1.0": 32, "0.97": 8},
    }


def _empty_attempt_bucket() -> dict[str, object]:
    return {
        **{field: 0 for field in training.ATTEMPT_BUCKET_COUNT_FIELDS},
        **{field: 0.0 for field in training.ATTEMPT_BUCKET_FLOAT_FIELDS},
        "proxy_reward_histogram": {},
    }


def test_trainer_history_requires_every_metric_at_exact_updates_and_rejects_extras() -> None:
    observed = training.coalesce_trainer_history([_trainer_row(0), _trainer_row(1, 0.2)], 2)

    assert observed[1]["entropy/all/mean"] == 0.2
    incomplete = _trainer_row(1)
    incomplete.pop("optim/grad_norm")
    with pytest.raises(ValueError, match="coverage differs"):
        training.coalesce_trainer_history([_trainer_row(0), incomplete], 2)
    with pytest.raises(ValueError, match="extra_steps"):
        training.coalesce_trainer_history([_trainer_row(0), _trainer_row(1), _trainer_row(2)], 2)
    with pytest.raises(ValueError, match="repeats"):
        training.coalesce_trainer_history([_trainer_row(0), {"step": 0, "optim/grad_norm": 1.0}], 1)


def test_group_prefix_keeps_stale_outcomes_missing_and_reports_per_tag() -> None:
    report = training.aggregate_group_prefix([_group(0), _group(2, stale=True)], (0, 1))

    overall = report["overall"]
    assert overall["raw_group_count"] == 2
    assert overall["reward_scored_group_count"] == 1
    assert overall["scored_valid_rollout_count"] == 128
    assert overall["C_A_candidate_count"] == 64
    assert overall["answer_wrong_count"] == 32
    assert overall["unscored_rollout_slot_count_by_cause"] == {"off_policy_cancellation": 128}
    assert report["per_neutral_tag"]["2"]["scored_valid_rollout_count"] == 0
    assert report["per_neutral_tag"]["5"]["raw_group_count"] == 0


def test_attempt_prefix_has_explicit_six_tag_zeros_and_separates_trainable_rows() -> None:
    buckets = {str(tag): _empty_attempt_bucket() for tag in range(6)}
    buckets["0"].update(
        {
            "consumed_rollout_count": 128,
            "trainable_rollout_count": 64,
            "gate_open_consumed_rollout_count": 128,
            "S_strict_positive_count": 16,
            "C_candidate_count": 64,
            "answer_wrong_count": 48,
            "K_effective_eligible_count": 64,
            "H_behavior_trigger_count": 4,
            "selected_extra_positive_count": 4,
            "negative_proxy_reward_count": 64,
            "proxy_reward_histogram": {"-0.03": 64, "0.0": 44, "1.0": 16, "0.97": 4},
        }
    )
    attempt = {"eligible_to_ship": True, "consumed_by_neutral_tag": buckets}
    rejected_buckets = {str(tag): _empty_attempt_bucket() for tag in range(6)}
    rejected_buckets["2"].update(
        {
            "consumed_rollout_count": 128,
            "C_candidate_count": 128,
            "answer_wrong_count": 0,
            "negative_proxy_reward_count": 128,
            "proxy_reward_histogram": {"-0.03": 128},
        }
    )
    rejected = {"eligible_to_ship": False, "consumed_by_neutral_tag": rejected_buckets}

    report = training.aggregate_attempt_prefix([attempt, rejected], (0, 1))

    assert report["overall"]["consumed_rollout_count"] == 128
    assert report["overall"]["trainable_rollout_count"] == 64
    assert report["per_neutral_tag"]["5"]["consumed_rollout_count"] == 0
    assert report["shipped_update_count"] == 1
    assert report["nonshipped_attempt_count"] == 1
    assert report["overall"]["C_A_candidate_count"] == 64
    assert report["nonshipped_selection_diagnostics"]["C_A_candidate_count"] == 128


def _write_wandb_record(store: datastore.DataStore, record: wandb_internal_pb2.Record) -> None:
    store.write(record)


def test_local_wandb_parser_is_strict_and_binds_run_record(tmp_path: Path) -> None:
    path = tmp_path / "run-testid.wandb"
    store = datastore.DataStore()
    store.open_for_write(str(path))
    run_record = wandb_internal_pb2.Record()
    run_record.run.run_id = "testid"
    run_record.run.display_name = "test"
    config_item = run_record.run.config.update.add()
    config_item.key = "output_dir"
    config_item.value_json = json.dumps(str(tmp_path))
    _write_wandb_record(store, run_record)
    history = wandb_internal_pb2.Record()
    for key, value in _trainer_row(0).items():
        item = history.history.item.add()
        item.nested_key.append(key)
        item.value_json = json.dumps(value)
    _write_wandb_record(store, history)
    store.close()

    scan = training._scan_local_wandb(
        path,
        selected_keys=training.TRAINER_METRIC_KEYS,
        row_trigger_keys=training.TRAINER_METRIC_KEYS,
    )

    assert scan["run"]["run_id"] == "testid"
    assert training.coalesce_trainer_history(scan["selected_rows"], 1)[0]["optim/grad_norm"] == 0.1

    corrupt = tmp_path / "run-corrupt.wandb"
    corrupt.write_bytes(path.read_bytes()[:-3])
    with pytest.raises(ValueError, match="invalid|FIRST/MIDDLE|continuation"):
        training._scan_local_wandb(
            corrupt,
            selected_keys=training.TRAINER_METRIC_KEYS,
            row_trigger_keys=training.TRAINER_METRIC_KEYS,
        )


def test_stability_uses_checkpoint_minus_one_and_raw_cancellations_are_bracketed() -> None:
    history = training.coalesce_trainer_history([_trainer_row(0, 0.1), _trainer_row(1, 0.2)], 2)
    stability = training._stability_readout(history, 2)
    periodic = training.coalesce_orchestrator_periodic(
        [
            {
                "dispatcher/cancelled/train": 0,
                "dispatcher/off_policy_level_max": 1,
                "dispatcher/off_policy_level_mean": 0.5,
                "train_sink/groups_finalized": 9,
                "_timestamp": 1.0,
            },
            {
                "dispatcher/cancelled/train": 4,
                "dispatcher/off_policy_level_max": 2,
                "dispatcher/off_policy_level_mean": 1.0,
                "train_sink/groups_finalized": 11,
                "_timestamp": 2.0,
            },
        ]
    )
    bounds = training._periodic_cancellation_bounds(periodic, 10)

    assert stability["last_update_step"] == 1
    assert stability["last_update"]["entropy/all/mean"] == 0.2
    assert bounds["lower_tick"]["finalized_groups"] == 9
    assert bounds["upper_tick"]["finalized_groups"] == 11
    assert bounds["cumulative_cancelled_train_rollout_upper_bound"] == 4
    fallback = training._periodic_cancellation_bounds(
        periodic[:1],
        10,
        exact_final_cancelled=7,
        final_group_count=12,
    )
    assert fallback["upper_tick"] is None
    assert fallback["cumulative_cancelled_train_rollout_upper_bound"] == 7
    assert fallback["upper_bound_source"] == "exact_final_log_total"


def test_training_consumer_itself_is_authority_pinned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = []

    def validate(authority, *, name, implementation_path):
        observed.append((authority, name, implementation_path.resolve()))
        digest = "a" * 64 if name == "training_readout_consumer" else "b" * 64
        return {"path": str(implementation_path.resolve()), "size_bytes": 1, "sha256": digest}

    monkeypatch.setattr(training.postrun_authority, "validate_recorded_implementation", validate)
    monkeypatch.setattr(
        training,
        "_build_run_readouts",
        lambda run, factors, authority, **kwargs: ([], {"run": run["run_id"]}),
    )
    authority = {
        "postrun_control_source": {},
        "training_readout_contract": {
            "completion_receipt_implementation": {
                "path": str(Path(training.training_completion.__file__).resolve()),
                "size_bytes": 1,
                "sha256": "b" * 64,
            },
            "completion_receipt_artifact_type": training.training_completion.ARTIFACT_TYPE,
            "completion_receipt_filename": training.training_completion.RECEIPT_NAME,
            "completion_receipt_dispatch_stage": training.training_completion.STAGE1_DISPATCH_STAGE,
            "stage2_completion_receipt_supported": False,
            "validated_adjacent_receipt_required_per_eligible_run": True,
            "completion_receipt_must_bind_allocation_stdout_and_stderr": True,
            "completion_receipt_must_bind_all_mutable_training_readout_inputs": True,
        },
    }
    plan = {"study_id": "study", "runs": [{"run_id": "run-a"}]}
    factors = {
        "run-a": {
            "run_id": "run-a",
            "block_seed": 1,
            "family": "g",
            "dose": 0.1,
        }
    }

    report = training.build_training_readouts(plan, factors, authority)

    assert observed == [
        (authority, "training_readout_consumer", Path(training.__file__).resolve()),
        (
            authority,
            "training_completion_materializer",
            Path(training.training_completion.__file__).resolve(),
        ),
    ]
    assert report["provenance"]["implementation"]["sha256"] == "a" * 64
    assert report["payload_without_self_hash_sha256"] == training.eval_plan.canonical_json_sha256(
        {key: value for key, value in report.items() if key != "payload_without_self_hash_sha256"}
    )


def test_custom_completion_validator_is_checked_before_and_after_each_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    implementation_path = tmp_path / "completion.py"
    implementation_path.write_text("# pinned completion validator\n", encoding="utf-8")
    implementation = training.eval_plan.file_identity(implementation_path)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    receipt = {
        "artifact_type": "stage2_completion",
        "dispatch_stage": "stage2_remaining",
        "implementation": {"repository_path": "completion.py", **implementation},
        "completion_evidence": {},
    }
    receipt_path = run_dir / "stage2_completion.json"
    receipt_path.write_bytes(training.eval_plan.canonical_json_bytes(receipt))
    validation = {"identity": training.eval_plan.file_identity(receipt_path), "receipt": receipt}
    calls = []

    def validate(run, authority):
        calls.append((run, authority))
        return validation

    def build(run, factors, authority, *, completion_validator):
        before = completion_validator(run, authority)
        after = completion_validator(run, authority)
        assert before == after == validation
        return [], {"completion": before["identity"]}

    monkeypatch.setattr(
        training.postrun_authority,
        "validate_recorded_implementation",
        lambda authority, *, name, implementation_path: {
            "path": str(implementation_path.resolve()),
            "size_bytes": 1,
            "sha256": "a" * 64,
        },
    )
    monkeypatch.setattr(training, "_build_run_readouts", build)
    run = {"run_id": "run-a", "run_dir": str(run_dir)}
    authority = {"postrun_control_source": {}}
    contract = {
        "implementation": implementation,
        "artifact_type": "stage2_completion",
        "filename": "stage2_completion.json",
        "dispatch_stage": "stage2_remaining",
        "validated_adjacent_receipt_required_before_and_after_each_run_readout": True,
        "completion_receipt_must_bind_allocation_stdout_and_stderr": True,
        "completion_receipt_must_bind_all_mutable_training_readout_inputs": True,
    }

    report = training.build_training_readouts(
        {"study_id": "study", "runs": [run]},
        {"run-a": {"run_id": "run-a"}},
        authority,
        completion_validator=validate,
        completion_contract=contract,
    )

    assert calls == [(run, authority), (run, authority)]
    assert report["provenance"]["completion_receipt_contract"] == contract


def test_training_readouts_require_and_bind_adjacent_completion_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identities = {
        name: {"path": f"/{name}", "size_bytes": index + 1, "sha256": f"{index + 1:x}" * 64}
        for index, name in enumerate(
            (
                "trainer_config",
                "orchestrator_config",
                "group_stats",
                "batch_attempts",
                "trainer_console",
                "orchestrator_console",
                "trainer_wandb",
                "orchestrator_wandb",
                "stable",
            )
        )
    }
    receipt = {
        "payload_without_self_hash_sha256": "f" * 64,
        "terminal_allocation": {"row": {"job_id": 123}},
        "completion_evidence": {
            "resolved_training_configs": {
                "trainer": identities["trainer_config"],
                "orchestrator": identities["orchestrator_config"],
            },
            "training_group_ledger": identities["group_stats"],
            "training_batch_attempt_ledger": identities["batch_attempts"],
            "trainer_console_log": identities["trainer_console"],
            "orchestrator_console_log": identities["orchestrator_console"],
            "local_wandb_streams": {
                "trainer": identities["trainer_wandb"],
                "orchestrator": identities["orchestrator_wandb"],
            },
            "final_stable_marker": identities["stable"],
            "final_checkpoint_step": 1500,
        },
    }
    validation = {"identity": {"path": "/receipt", "size_bytes": 1, "sha256": "e" * 64}, "receipt": receipt}
    calls = []
    monkeypatch.setattr(
        training.training_completion,
        "validate_adjacent_receipt",
        lambda run_dir, **kwargs: calls.append((run_dir, kwargs)) or validation,
    )
    initial_identity = {"path": "/intent", "size_bytes": 1, "sha256": "d" * 64}
    run = {
        "run_dir": str(tmp_path),
        "launch_binding": {"arm_filename": "b20260808_g_p0125.toml"},
    }
    authority = {"initial_launch_authority": {"intent": initial_identity}}

    before = training._validated_completion_receipt(run, authority)
    provenance = {
        "resolved_configs": {
            "trainer": identities["trainer_config"],
            "orchestrator": identities["orchestrator_config"],
        },
        "training_replay_inputs": {
            "train_group_stats": identities["group_stats"],
            "train_batch_attempts": identities["batch_attempts"],
        },
        "trainer_console": {"identity": identities["trainer_console"]},
        "orchestrator_console": {"identity": identities["orchestrator_console"]},
        "trainer_local_wandb": {"identity": identities["trainer_wandb"]},
        "orchestrator_local_wandb": {"identity": identities["orchestrator_wandb"]},
        "final_checkpoint": {"stable_marker": identities["stable"]},
        "final_step": 1500,
    }

    binding = training._bind_completion_receipt(before, before, provenance)

    assert binding["identity"] == validation["identity"]
    assert calls == [
        (
            tmp_path.resolve(),
            {
                "arm_filename": "b20260808_g_p0125.toml",
                "initial_intent_identity": initial_identity,
            },
        )
    ]
    changed = json.loads(json.dumps(provenance))
    changed["final_step"] = 1550
    with pytest.raises(ValueError, match="final_step"):
        training._bind_completion_receipt(before, before, changed)


def test_exact_training_replay_uses_authority_recorded_cross_snapshot_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replay_path = tmp_path / "old-snapshot" / "user" / "tianhaowu" / "rsci" / "analyze_masked_verifier_attempts.py"
    replay_path.parent.mkdir(parents=True)
    replay_path.write_text("# pinned replay\n", encoding="utf-8")
    replay_identity = training.eval_plan.file_identity(replay_path)
    authority = {
        "postrun_control_source": {
            "implementations": {
                "training_replay": replay_identity,
            }
        }
    }
    orchestrator_identity = {"path": "/orchestrator", "size_bytes": 1, "sha256": "b" * 64}
    groups_identity = {"path": "/groups", "size_bytes": 2, "sha256": "c" * 64}
    attempts_identity = {"path": "/attempts", "size_bytes": 3, "sha256": "d" * 64}
    run = {
        "run_dir": str(tmp_path / "run"),
        "resolved_configs": {"orchestrator": orchestrator_identity},
        "clock_audit": {"group_stats": groups_identity, "batch_attempts": attempts_identity},
    }
    replay = {
        "analysis": "masked_verifier_defect_attempts_v6",
        "provenance": {
            "analyzer": replay_identity,
            "inputs": {
                "orchestrator_config": orchestrator_identity,
                "train_group_stats": groups_identity,
                "train_batch_attempts": attempts_identity,
            },
        },
        "validation": {
            key: True
            for key in {
                "candidate_scope_effective_eligibility_replayed",
                "raw_digest_masks_and_ranks_replayed",
                "defect_and_shuffle_draws_replayed",
                "group_gate_draw_open_state_and_conditional_rate_replayed",
                "neutral_tag_gate_and_reference_metrics_replayed",
                "known_cost_B_S_M_untaxed_taxed_and_net_rewards_replayed",
                "attempt_consumption_replayed_by_neutral_tag",
                "reward_vectors_replayed",
            }
        },
    }
    calls = []
    monkeypatch.setattr(
        training.postrun_authority,
        "validate_recorded_implementation",
        lambda authority, *, name, implementation_path: replay_identity,
    )
    monkeypatch.setattr(
        training.launch,
        "_run_exact_validator",
        lambda path, arguments: calls.append((path, arguments)) or replay,
    )

    assert training._validate_replay(run, authority) == replay
    assert calls == [(replay_path.resolve(), [str((tmp_path / "run").resolve())])]
