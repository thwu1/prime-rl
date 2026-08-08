import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest
from analyze_correlated_defect_preflight import (
    EXPECTED_TEMPLATES,
    FALSE_POSITIVE_PROBABILITY,
    GROUP_GATE_CONDITIONAL_PROBABILITY,
    GROUP_GATE_PROBABILITY,
    PHYSICAL_GROUP_SIZE,
    RUNTIME_GROUP_GATE_CONDITIONAL_PROBABILITY,
    FrozenGroup,
    arm_group_moments,
    exact_l_pair_covariance,
    group_gate_draw,
    group_gate_pair_covariance,
    load_launch_config_contract,
    realized_seed_gate_exposure,
    sample_slot_draw,
    summarize_histogram,
    support_bounds,
    template_persistent_summary,
    write_json_atomic,
)
from analyze_masked_verifier_attempts import group_gate_draw as live_replay_group_gate_draw
from analyze_masked_verifier_attempts import sample_slot_draw as live_replay_sample_slot_draw


def test_support_extremes_have_matched_marginals_and_exact_covariances() -> None:
    candidate_count = 37
    summaries = {
        arm: arm_group_moments(candidate_count, arm) for arm in ("iid", "exact_l1", "group_gate", "all_or_none")
    }
    expected = candidate_count * FALSE_POSITIVE_PROBABILITY
    assert {summary.expected_triggers for summary in summaries.values()} == {expected}
    assert support_bounds(candidate_count) == (FALSE_POSITIVE_PROBABILITY, expected)
    assert summaries["exact_l1"].expected_any_trigger == expected
    assert summaries["all_or_none"].expected_any_trigger == FALSE_POSITIVE_PROBABILITY
    assert summaries["group_gate"].expected_any_trigger == pytest.approx(
        GROUP_GATE_PROBABILITY * (1 - (1 - GROUP_GATE_CONDITIONAL_PROBABILITY) ** candidate_count)
    )
    assert exact_l_pair_covariance(1) == pytest.approx(-(FALSE_POSITIVE_PROBABILITY**2))
    assert group_gate_pair_covariance() == pytest.approx(2 * FALSE_POSITIVE_PROBABILITY**2)


def test_l1_and_all_or_none_attain_frechet_activation_bounds() -> None:
    for candidate_count in (1, 2, 64, PHYSICAL_GROUP_SIZE):
        lower, upper = support_bounds(candidate_count)
        assert arm_group_moments(candidate_count, "exact_l1").expected_any_trigger == upper
        assert arm_group_moments(candidate_count, "all_or_none").expected_any_trigger == lower
    all_candidate_burst = arm_group_moments(PHYSICAL_GROUP_SIZE, "all_or_none")
    assert all_candidate_burst.expected_all_slots_triggered == FALSE_POSITIVE_PROBABILITY


def test_histogram_summary_separates_any_trigger_from_strict_dead_nucleation() -> None:
    histogram = Counter(
        {
            (0, 0): 2,
            (0, 4): 3,
            (0, PHYSICAL_GROUP_SIZE): 1,
            (1, 4): 2,
        }
    )
    burst = summarize_histogram(histogram, "all_or_none")
    assert burst["groups"] == 8
    assert burst["candidate_slots"] == 148
    assert burst["expected_trigger_slots_E_H"] == pytest.approx(148 / 400)
    assert burst["expected_any_trigger_groups"] == pytest.approx(6 / 400)
    assert burst["expected_strict_dead_nucleation_groups"] == pytest.approx(3 / 400)

    l1 = summarize_histogram(histogram, "exact_l1")
    assert l1["expected_any_trigger_groups"] == l1["expected_trigger_slots_E_H"]
    assert l1["trigger_count_variance_design_effect_vs_iid"] < 1


def test_template_persistence_matches_group_gate_one_group_law() -> None:
    template_histograms = {
        template: Counter({(0, candidate_count): 10})
        for template, candidate_count in zip(EXPECTED_TEMPLATES, (2, 3, 4), strict=True)
    }
    summary = template_persistent_summary(template_histograms, projection_factor=0.5)
    expected_candidates = 90
    assert summary["candidate_slots"] == expected_candidates
    assert summary["expected_trigger_slots_E_H"] == pytest.approx(expected_candidates * FALSE_POSITIVE_PROBABILITY)
    expected_activation = sum(
        10 * GROUP_GATE_PROBABILITY * (1 - (1 - GROUP_GATE_CONDITIONAL_PROBABILITY) ** c) for c in (2, 3, 4)
    )
    assert summary["expected_any_trigger_groups"] == pytest.approx(expected_activation)
    assert summary["same_template_pair_covariance_including_across_groups"] == pytest.approx(
        2 * FALSE_POSITIVE_PROBABILITY**2
    )
    projected = summary["projected_proportional_hard_subset"]
    assert projected["expected_trigger_slots_E_H"] == pytest.approx(summary["expected_trigger_slots_E_H"] / 2)
    assert projected["expected_any_trigger_groups"] == pytest.approx(expected_activation / 2)


def test_atomic_report_write_is_deterministic(tmp_path: Path) -> None:
    payload = {"z": 1, "a": [2, 3]}
    output = tmp_path / "nested" / "report.json"
    first = write_json_atomic(output, payload)
    content = output.read_bytes()
    second = write_json_atomic(output, payload)
    assert output.read_bytes() == content
    assert first == second
    assert json.loads(content) == payload


def test_six_arm_launch_contract_is_hash_bound_and_latin_square_balanced() -> None:
    contract, identities = load_launch_config_contract()
    arms = contract["arms"]
    assert len(arms) == 6
    assert set(identities) == {"base", "common", *arms}
    template_arms = [arm for arm in arms.values() if arm["gate_mode"] == "template"]
    assert {arm["selected_template"] for arm in template_arms} == {
        "crazy_zootopia",
        "movie_festival_awards",
        "teachers_in_school",
    }
    assert all(arm["nominal_p"] == 0.0025 for arm in arms.values())
    assert all(arm["gate_probability_alpha"] == 1 / 3 for arm in arms.values())
    assert all(arm["conditional_q"] == pytest.approx(0.0075) for arm in arms.values())
    assert all(len(identity.sha256) == 64 for identity in identities.values())


def test_realized_seed_gate_exposure_replays_hash_and_template_assignment() -> None:
    groups = tuple(
        FrozenGroup(
            operation=21,
            prompt_index=index,
            sample_id=f"sample-{index}",
            template=template,
            strict_count=0,
            candidate_count=10 * (index + 1),
            candidate_slots=tuple(range(10 * (index + 1))),
        )
        for index, template in enumerate(EXPECTED_TEMPLATES)
    )

    result = realized_seed_gate_exposure(groups, projection_factor=0.5)

    for seed in (20260805, 20260806, 20260807):
        for group in groups:
            assert group_gate_draw(group.sample_id, seed) == live_replay_group_gate_draw(group.sample_id, seed)
    seed_05 = result["per_seed"]["20260805"]
    assert seed_05["selected_template"] == "crazy_zootopia"
    assert seed_05["template_gate_T"]["gate_open_candidate_slots"] == 10
    assert seed_05["template_gate_T"]["expected_trigger_slots_E_H_at_q"] == pytest.approx(0.075)
    expected_realized_h = sum(
        sample_slot_draw(groups[0].sample_id, slot, 20260805) < RUNTIME_GROUP_GATE_CONDITIONAL_PROBABILITY
        for slot in groups[0].candidate_slots
    )
    assert seed_05["template_gate_T"]["realized_trigger_slots_H"] == expected_realized_h
    for slot in groups[0].candidate_slots:
        assert sample_slot_draw(groups[0].sample_id, slot, 20260805) == live_replay_sample_slot_draw(
            groups[0].sample_id,
            slot,
            20260805,
            shuffled=False,
        )
    assert result["balance_gate_basis"] == "conditional_expectation_given_fixed_gates"
    assert "paired_G_over_T_realized_ratios" in seed_05
    pooled = result["pooled_realized_coin_replay"]
    assert pooled["group_gate_G"]["realized_trigger_slots_H"] == sum(
        seed["group_gate_G"]["realized_trigger_slots_H"] for seed in result["per_seed"].values()
    )
    assert result["all_seed_expected_exposure_balance_pass"] is False
    assert seed_05["template_gate_T"]["projected_proportional_12k_op10_40_hard_contribution"][
        "expected_trigger_slots_E_H_at_q"
    ] == pytest.approx(0.0375)


def test_known_cost_boundary_preflight_replays_exact_configs_reward_law_and_bit_vectors() -> None:
    import analyze_known_cost_boundary_preflight as known_cost

    tokenizer_path = Path(
        "/checkpoint/ram-h100-2/tianhaowu/rsci/hf/hub/"
        "models--Interplay-LM-Reasoning--extrapolation_rl/snapshots/"
        "4861bd030e6fb92d94be3a1cecab89c2fac4b94a/"
        "id2-10_0.2easy_0.3medium_0.5hard/base"
    )
    config_audit, identities, arms = known_cost.audit_launch_configs(
        known_cost.DEFAULT_BASE_CONFIG,
        known_cost.DEFAULT_CONFIG_ROOT,
        known_cost.DEFAULT_BANK_ROOT,
        tokenizer_path,
    )
    assert config_audit["arm_count"] == 30
    assert len(arms) == 30
    assert set(identities) == {"base", "common", *(arm.filename for arm in arms)}

    representative_arms = tuple(
        next(arm for arm in arms if arm.family == family) for family in ("clean", "tax", "g", "t")
    )
    runtime_audit = known_cost.audit_runtime_law(representative_arms)
    assert runtime_audit["contract_count"] == 4
    assert runtime_audit["synthetic_categories"] == ["strict", "candidate", "answer_wrong", "invalid"]
    assert runtime_audit["metric_count"] == 41
    assert runtime_audit["scalar_metric_comparisons"] > 0

    lower = known_cost.PackedBitVector(10)
    upper = known_cost.PackedBitVector(10)
    for index in (0, 3, 9):
        lower.set(index)
        upper.set(index)
    upper.set(5)
    assert lower.is_subset_of(upper)
    assert not upper.is_subset_of(lower)
    assert lower.record() == lower.record()
    assert lower.record()["one_count"] == 3


def test_known_cost_launch_intent_selects_preregistered_arms_and_requires_adjacent_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import materialize_known_cost_boundary_launch as launch

    full_result = {
        "decision": {
            "eligible_design": "full_30_arm_grid",
            "full_grid_eligible": True,
        }
    }
    smoke_result = {
        "decision": {
            "eligible_design": "four_arm_smoke_screen",
            "full_grid_eligible": False,
        }
    }
    assert launch.eligible_arm_filenames(full_result)[1] == tuple(
        arm.filename for arm in launch.preflight.arm_contracts()
    )
    assert launch.eligible_arm_filenames(smoke_result)[1] == launch.SMOKE_ARM_FILENAMES

    tokenizer = tmp_path / "tokenizer"
    tokenizer.mkdir()
    dataset = tmp_path / "train.jsonl"
    manifest = tmp_path / "train.jsonl.manifest.json"
    dataset.write_text("{}\n", encoding="utf-8")
    manifest.write_text("{}\n", encoding="utf-8")
    dataset_identity = launch.file_identity(dataset)
    manifest_identity = launch.file_identity(manifest)
    tokenizer_sha = "a" * 64
    arm_report = {"block_seed": 20260808}
    preflight_report = {
        "bank_audit": {
            "20260808": {
                "output": dataset_identity,
                "manifest": manifest_identity,
            }
        }
    }
    launch_inputs = {
        "datasets": [
            {
                **dataset_identity,
                "resolved_path": dataset_identity["path"],
                "environments": [{"phase": "train"}],
                "adjacent_manifest": {
                    **manifest_identity,
                    "resolved_path": manifest_identity["path"],
                    "artifact_type": "rsci_known_cost_neutral_tag_bank",
                    "declared_dataset_sha256": dataset_identity["sha256"],
                    "declared_dataset_size_bytes": dataset_identity["size_bytes"],
                    "tag_tokenization": {
                        "configured_tokenizer_path": str(tokenizer.resolve()),
                        "configured_tokenizer_sha256": tokenizer_sha,
                        "equal_token_counts": True,
                        "common_token_count": 13,
                    },
                },
            }
        ],
        "tokenizer": {"sha256": tokenizer_sha},
    }
    assert (
        launch._known_cost_train_input(
            launch_inputs,
            arm_report,
            preflight_report,
            tokenizer,
        )["sha256"]
        == dataset_identity["sha256"]
    )
    launch_inputs["datasets"][0].pop("adjacent_manifest")
    with pytest.raises(ValueError, match="adjacent dataset manifest"):
        launch._known_cost_train_input(
            launch_inputs,
            arm_report,
            preflight_report,
            tokenizer,
        )

    intent = {
        "schema_version": launch.SCHEMA_VERSION,
        "artifact_type": launch.ARTIFACT_TYPE,
        "inputs": {
            "run_root": str(tmp_path),
            "preflight_report": str(tmp_path / "preflight.json"),
            "kernel_root": str(tmp_path / "kernel"),
            "kernel_reconciliation": str(tmp_path / "kernel" / launch.KERNEL_RECONCILIATION_NAME),
            "tokenizer_path": str(tokenizer.resolve()),
        },
    }
    intent["payload_without_self_hash_sha256"] = launch.canonical_json_sha256(intent)
    intent_path = tmp_path / launch.INTENT_NAME
    launch.write_intent_atomic(intent_path, intent)
    replay_calls = []
    monkeypatch.setattr(launch, "build_intent", lambda **kwargs: replay_calls.append(kwargs) or intent)
    assert launch.validate_intent(intent_path, tokenizer_path=tokenizer)["intent"] == intent
    assert replay_calls[-1]["kernel_reconciliation_path"] == (tmp_path / "kernel" / launch.KERNEL_RECONCILIATION_NAME)
    intent_path.chmod(0o644)
    with pytest.raises(ValueError, match="writable"):
        launch.validate_intent(intent_path, tokenizer_path=tokenizer)
    intent_path.chmod(0o444)
    assert launch.write_intent_atomic(intent_path, intent) == launch.file_identity(intent_path)
    assert intent_path.with_suffix(".json.lock").is_file()
    with pytest.raises(FileExistsError, match="immutable submission intent"):
        launch.write_intent_atomic(intent_path, {**intent, "study_id": "tampered"})
    relocated = tmp_path / "relocated" / launch.INTENT_NAME
    relocated.parent.mkdir()
    relocated.write_bytes(intent_path.read_bytes())
    relocated.chmod(0o444)
    with pytest.raises(ValueError, match="not adjacent to its recorded run root"):
        launch.validate_intent(relocated, tokenizer_path=tokenizer)

    kernel_path = tmp_path / "kernel.json"
    kernel_path.write_text("{}\n", encoding="utf-8")
    kernel_identity = launch.file_identity(kernel_path)
    kernel_result = {
        "decision": {
            "eligible_design": "four_arm_smoke_screen",
            "finite_step_ordering_passed": False,
        },
        "kernel_summary": {"median_off_diagonal": 0.75},
    }
    validation_path = tmp_path / "kernel_validation.json"
    validation = {
        "command": "validate-result",
        "eligible_design": "four_arm_smoke_screen",
        "finite_step_ordering_passed": False,
        "median_off_diagonal": 0.75,
        "output": str(kernel_path.resolve()),
        "output_sha256": kernel_identity["sha256"],
    }
    validation_path.write_bytes(launch.canonical_json_bytes(validation))
    assert launch._optional_kernel_validation(
        validation_path,
        kernel_identity,
        kernel_result,
    )["identity"]["path"] == str(validation_path.resolve())
    validation.pop("command")
    validation_path.write_bytes(launch.canonical_json_bytes(validation))
    with pytest.raises(ValueError, match="exact kernel validation summary schema"):
        launch._optional_kernel_validation(
            validation_path,
            kernel_identity,
            kernel_result,
        )


def test_kernel_receipt_replays_exact_cross_snapshot_finalizer_with_optional_live_scheduler(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import finalize_known_cost_kernel_execution as finalizer
    import materialize_known_cost_boundary_launch as launch

    snapshot = tmp_path / "old-control-snapshot"
    validator_path = snapshot / finalizer.IMPLEMENTATION_REPOSITORY_PATH
    validator_path.parent.mkdir(parents=True)
    validator_path.write_text("# immutable historical finalizer\n", encoding="utf-8")
    validator_identity = launch.file_identity(validator_path)
    receipt = {field: {} for field in finalizer.RECEIPT_TOP_FIELDS}
    receipt.update(
        {
            "schema_version": finalizer.SCHEMA_VERSION,
            "artifact_type": finalizer.ARTIFACT_TYPE,
            "finalizer_source_provenance": {"snapshot_path": str(snapshot)},
            "implementation": {
                "repository_path": finalizer.IMPLEMENTATION_REPOSITORY_PATH,
                "size_bytes": validator_identity["size_bytes"],
                "sha256": validator_identity["sha256"],
            },
            "scheduler": {
                "gpu_job": {"job_id": 101},
                "validator_job": {"job_id": 102},
            },
            "gpu_run_summary": {"eligible_design": "four_arm_smoke_screen"},
        }
    )
    receipt.pop("payload_without_self_hash_sha256")
    receipt["payload_without_self_hash_sha256"] = launch.canonical_json_sha256(receipt)
    receipt_path = tmp_path / finalizer.RECEIPT_NAME
    receipt_path.write_bytes(launch.canonical_json_bytes(receipt))
    receipt_path.chmod(0o444)
    receipt_identity = launch.file_identity(receipt_path)
    expected_summary = {
        "command": "validate",
        "receipt": receipt_identity,
        "gpu_job_id": 101,
        "validator_job_id": 102,
        "eligible_design": "four_arm_smoke_screen",
    }
    calls = []
    monkeypatch.setattr(
        launch,
        "_run_exact_validator",
        lambda path, arguments: calls.append((path, arguments)) or expected_summary,
    )

    live = launch._validated_kernel_execution_receipt(receipt_path, verify_scheduler=True)
    static = launch._validated_kernel_execution_receipt(receipt_path, verify_scheduler=False)

    assert live == static
    assert calls == [
        (
            validator_path.resolve(),
            ["validate", "--receipt", str(receipt_path.resolve()), "--verify-scheduler"],
        ),
        (
            validator_path.resolve(),
            ["validate", "--receipt", str(receipt_path.resolve())],
        ),
    ]
    assert live["validator"]["sha256"] == validator_identity["sha256"]

    validator_path.write_text("# changed historical finalizer\n", encoding="utf-8")
    with pytest.raises(ValueError, match="finalizer bytes differ"):
        launch._validated_kernel_execution_receipt(receipt_path, verify_scheduler=False)

    wrong_path_receipt = {**receipt, "implementation": {**receipt["implementation"]}}
    wrong_path_receipt["implementation"]["repository_path"] = "user/tianhaowu/rsci/not_the_finalizer.py"
    wrong_path_receipt.pop("payload_without_self_hash_sha256")
    wrong_path_receipt["payload_without_self_hash_sha256"] = launch.canonical_json_sha256(wrong_path_receipt)
    wrong_path = tmp_path / "wrong-path-receipt.json"
    wrong_path.write_bytes(launch.canonical_json_bytes(wrong_path_receipt))
    wrong_path.chmod(0o444)
    with pytest.raises(ValueError, match="wrong finalizer repository path"):
        launch._validated_kernel_execution_receipt(wrong_path, verify_scheduler=False)


def test_kernel_reconciliation_live_sacct_excludes_only_durable_script_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import finalize_known_cost_kernel_execution as finalizer
    import materialize_known_cost_boundary_launch as launch

    terminal = {
        "job_id": "job",
        "job_name": "name",
        "state": "COMPLETED",
        "exit_code": "0:0",
        "submit_time": "2026-08-07T00:00:00Z",
        "start_time": "2026-08-07T00:01:00Z",
        "end_time": "2026-08-07T00:02:00Z",
        "elapsed_seconds": 60,
        "qos": "qos",
        "account": "ram",
        "comment": "",
        "time_limit": "00:45:00",
        "time_limit_minutes": 45,
    }
    actual = {
        finalizer.GPU_JOB_ID: {**terminal, "job_id": finalizer.GPU_JOB_ID},
        finalizer.VALIDATOR_JOB_ID: {**terminal, "job_id": finalizer.VALIDATOR_JOB_ID},
    }
    receipt = {
        "scheduler": {
            "gpu_job": {
                **actual[finalizer.GPU_JOB_ID],
                "submitted_batch_script_sha256": "a" * 64,
            },
            "validator_job": {
                **actual[finalizer.VALIDATOR_JOB_ID],
                "submitted_batch_script_sha256": "b" * 64,
            },
        }
    }
    monkeypatch.setattr(finalizer, "_sacct_job", lambda job_id: job_id)
    monkeypatch.setattr(
        finalizer,
        "_completed_scheduler_record",
        lambda job_id, **_: actual[job_id],
    )
    assert launch._live_terminal_scheduler_records(receipt) == {
        "gpu_job": actual[finalizer.GPU_JOB_ID],
        "validator_job": actual[finalizer.VALIDATOR_JOB_ID],
    }

    actual[finalizer.GPU_JOB_ID] = {**actual[finalizer.GPU_JOB_ID], "state": "FAILED"}
    with pytest.raises(ValueError, match="differs from live terminal sacct"):
        launch._live_terminal_scheduler_records(receipt)

    receipt["scheduler"]["gpu_job"]["submitted_batch_script_sha256"] = hashlib.sha256(b"").hexdigest()
    with pytest.raises(ValueError, match="empty-output"):
        launch._live_terminal_scheduler_records(receipt)


def test_finalizer_script_capture_requires_read_only_bytes_inside_controller_retention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import materialize_known_cost_boundary_launch as launch

    script = tmp_path / launch.FINALIZER_SCRIPT_NAME
    script.write_bytes(b"submitted script\n")
    script.chmod(0o444)
    monkeypatch.setattr(launch, "FINALIZER_SCRIPT_SHA256", launch.sha256_file(script))
    monkeypatch.setattr(launch, "FINALIZER_SCRIPT_SIZE_BYTES", script.stat().st_size)
    finalizer_job = {"end_time": "2026-08-08T00:22:34Z"}
    end = launch.kernel_execution._parse_utc(finalizer_job["end_time"], "end").timestamp()
    capture_ns = int((end + 300) * 1_000_000_000)
    os.utime(script, ns=(capture_ns, capture_ns))
    capture = launch._fixed_finalizer_script_capture(tmp_path, finalizer_job)
    assert capture["nonempty_capture"] is True
    assert capture["read_only_capture"] is True
    assert capture["identity"]["sha256"] == launch.sha256_file(script)

    expired_ns = int((end + launch.CONTROLLER_MIN_JOB_AGE_SECONDS + 1) * 1_000_000_000)
    os.utime(script, ns=(expired_ns, expired_ns))
    with pytest.raises(ValueError, match="outside controller retention"):
        launch._fixed_finalizer_script_capture(tmp_path, finalizer_job)


def test_kernel_reconciliation_is_write_once_and_later_replay_is_static(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import finalize_known_cost_kernel_execution as finalizer
    import materialize_known_cost_boundary_launch as launch

    def terminal(job_id: str, name: str, qos: str) -> dict[str, object]:
        return {
            "job_id": job_id,
            "job_name": name,
            "state": "COMPLETED",
            "exit_code": "0:0",
            "submit_time": "2026-08-07T00:00:00Z",
            "start_time": "2026-08-08T00:00:00Z",
            "end_time": "2026-08-08T00:01:00Z",
            "elapsed_seconds": 60,
            "qos": qos,
            "account": "ram",
            "comment": "",
            "time_limit": "00:30:00",
            "time_limit_minutes": 30,
        }

    gpu = terminal(finalizer.GPU_JOB_ID, finalizer.GPU_JOB_NAME, finalizer.GPU_FINAL_QOS)
    validator = terminal(finalizer.VALIDATOR_JOB_ID, finalizer.VALIDATOR_JOB_NAME, finalizer.VALIDATOR_QOS)
    receipt = {
        "scheduler": {
            "gpu_job": {**gpu, "submitted_batch_script_sha256": "a" * 64},
            "validator_job": {**validator, "submitted_batch_script_sha256": "b" * 64},
        }
    }
    receipt_identity = {"path": str(tmp_path / "receipt.json"), "size_bytes": 1, "sha256": "c" * 64}
    validated = {
        "receipt": receipt,
        "identity": receipt_identity,
        "validator": {"path": "/snapshot/finalizer.py", "size_bytes": 1, "sha256": "d" * 64},
        "validator_source_provenance": {"snapshot_path": "/snapshot"},
        "validation_summary_sha256": "e" * 64,
    }
    finalizer_job = {
        **terminal(launch.FINALIZER_JOB_ID, launch.FINALIZER_JOB_NAME, launch.FINALIZER_QOS),
        "stdout_template": launch.FINALIZER_STDIO_TEMPLATE,
        "stderr_template": launch.FINALIZER_STDIO_TEMPLATE,
    }
    source = {"snapshot_path": "/successor"}
    capture = {"identity": {"sha256": launch.FINALIZER_SCRIPT_SHA256}}
    log = {"identity": {"sha256": launch.FINALIZER_LOG_SHA256}}
    mtime = {"mtime_ns": 1}
    monkeypatch.setattr(launch, "_validated_kernel_execution_receipt", lambda *args, **kwargs: validated)
    monkeypatch.setattr(launch, "_sacct_finalizer_job", lambda: finalizer_job)
    monkeypatch.setattr(
        launch,
        "_live_terminal_scheduler_records",
        lambda _: {"gpu_job": gpu, "validator_job": validator},
    )
    monkeypatch.setattr(launch, "_fixed_finalizer_script_capture", lambda *args: capture)
    monkeypatch.setattr(launch, "_fixed_finalizer_log_evidence", lambda *args: log)
    monkeypatch.setattr(launch, "_receipt_mtime_evidence", lambda *args: mtime)
    monkeypatch.setattr(launch, "_control_plane_source_provenance", lambda: source)

    payload = launch._build_kernel_reconciliation(tmp_path)
    path = tmp_path / launch.KERNEL_RECONCILIATION_NAME
    identity = launch.write_kernel_reconciliation_once(path, payload)
    monkeypatch.setattr(
        launch,
        "_live_terminal_scheduler_records",
        lambda _: (_ for _ in ()).throw(AssertionError("static replay queried Slurm")),
    )
    assert launch.validate_kernel_reconciliation(str(path))["identity"] == identity
    assert launch.write_kernel_reconciliation_once(path, payload) == identity

    with pytest.raises(FileExistsError, match="different kernel reconciliation"):
        launch.write_kernel_reconciliation_once(path, {**payload, "study_id": "tampered"})


def test_launch_materialize_requires_frozen_kernel_reconciliation_and_successor_source_is_current(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import materialize_known_cost_boundary_launch as launch

    calls = []
    intent = {
        "preregistered_decision": {
            "eligible_design": "four_arm_smoke_screen",
            "eligible_arm_count": 4,
        }
    }
    monkeypatch.setattr(launch, "build_intent", lambda **kwargs: calls.append(kwargs) or intent)
    monkeypatch.setattr(
        launch,
        "write_intent_atomic",
        lambda path, payload: {"path": str(path), "size_bytes": 1, "sha256": "a" * 64},
    )
    monkeypatch.setattr(
        launch,
        "parse_args",
        lambda: SimpleNamespace(
            command="materialize",
            run_root=tmp_path,
            preflight_report=tmp_path / "preflight.json",
            kernel_root=tmp_path / "kernel",
            tokenizer=tmp_path / "tokenizer",
            kernel_validation=None,
            kernel_reconciliation=tmp_path / "kernel" / launch.KERNEL_RECONCILIATION_NAME,
        ),
    )

    launch.main()

    assert calls[0]["kernel_reconciliation_path"] == (tmp_path / "kernel" / launch.KERNEL_RECONCILIATION_NAME)
    assert json.loads(capsys.readouterr().out)["command"] == "materialize"

    source_root, _ = launch._source_root(Path(launch.__file__))
    monkeypatch.setattr(
        launch.source_provenance,
        "verify_snapshot",
        lambda *args, **kwargs: {"snapshot_path": str(source_root)},
    )
    monkeypatch.setattr(
        launch,
        "_source_provenance_record",
        lambda *args, **kwargs: {"source_tree": "successor"},
    )
    provenance = launch._control_plane_source_provenance()
    assert provenance["snapshot_path"] == str(source_root)
    assert provenance["source_tree"] == "successor"
    assert provenance["implementations"]["dispatcher"]["path"] == str(
        source_root / launch.CONTROL_PLANE_REPOSITORY_PATHS["dispatcher"]
    )


def test_known_cost_generated_projection_is_type_strict_and_smoke_inventory_excludes_26_arms() -> None:
    import copy

    import materialize_known_cost_boundary_launch as launch

    expected = {
        "max_steps": 1,
        "seq_len": 8,
        "ckpt": {"interval": 1},
        "model": {"name": "model"},
        "tokenizer": {"name": "tokenizer"},
        "trainer": {
            "model": {"impl": "hf"},
            "optim": {"lr": 1.0},
            "scheduler": {"type": "constant"},
        },
        "inference": {
            "seed": 7,
            "model": {"max_model_len": 8},
            "parallel": {"tp": 1},
        },
        "orchestrator": {
            "batch_size": 2,
            "rollouts_per_example": 4,
            "train": {"env": [{"args": {"false_positive_rate": 1}}]},
            "eval": {"rollouts_per_example": 1},
        },
        "wandb": {"name": "run"},
        "weight_broadcast": {"type": "nccl"},
    }
    trainer = {
        "max_steps": 1,
        "model": {"name": "model", "seq_len": 8, "impl": "hf"},
        "tokenizer": {"name": "tokenizer"},
        "ckpt": {"interval": 1},
        "wandb": {"name": "run"},
        "weight_broadcast": {"type": "nccl"},
        "optim": {"lr": 1.0},
        "scheduler": {"type": "constant"},
    }
    orchestrator = {
        "max_steps": 1,
        "seq_len": 8,
        "group_size": 4,
        "batch_size": 2,
        "student": {"model": {"name": "model"}},
        "tokenizer": {"name": "tokenizer"},
        "ckpt": {"interval": 1},
        "wandb": {"name": "run"},
        "weight_broadcast": {"type": "nccl"},
        "train": {"env": [{"args": {"false_positive_rate": 1}}]},
        "eval": {"group_size": 1},
    }
    inference = {
        "seed": 7,
        "model": {"name": "model", "max_model_len": 8},
        "parallel": {"tp": 1},
        "weight_broadcast": {"type": "nccl"},
    }
    assert (
        launch._generated_scientific_projection(
            expected=expected,
            trainer=trainer,
            orchestrator=orchestrator,
            inference=inference,
        )
        == expected
    )
    type_forgery = copy.deepcopy(expected)
    type_forgery["orchestrator"]["train"]["env"][0]["args"]["false_positive_rate"] = 1.0
    with pytest.raises(ValueError, match="values differ"):
        launch._generated_scientific_projection(
            expected=type_forgery,
            trainer=trainer,
            orchestrator=orchestrator,
            inference=inference,
        )

    arm_reports = {
        arm.filename: {
            "block_seed": arm.seed,
            "condition": arm.condition,
            "output_dir": f"/runs/{arm.seed}/{arm.run_label}",
            "overlay_identity": {"sha256": arm.filename},
            "resolved_config_sha256": arm.filename,
        }
        for arm in launch.preflight.arm_contracts()
    }
    runs = [
        {
            "arm_filename": filename,
            "source_provenance": {"manifest": {"sha256": filename}},
            "sbatch": {"sha256": filename},
        }
        for filename in launch.SMOKE_ARM_FILENAMES
    ]
    inventory = launch._build_arm_inventory(
        arm_reports=arm_reports,
        eligible_filenames=launch.SMOKE_ARM_FILENAMES,
        design="four_arm_smoke_screen",
        runs=runs,
    )
    assert len(inventory) == 30
    assert sum(item["decision_status"] == "eligible" for item in inventory) == 4
    assert sum(item["decision_status"] == "excluded" for item in inventory) == 26
    assert all("sbatch" not in item for item in inventory if item["decision_status"] == "excluded")
    with pytest.raises(ValueError, match="do not equal"):
        launch._build_arm_inventory(
            arm_reports=arm_reports,
            eligible_filenames=launch.SMOKE_ARM_FILENAMES,
            design="four_arm_smoke_screen",
            runs=[*runs, {**runs[0], "arm_filename": "b20260808_clean.toml"}],
        )


def test_known_cost_kernel_receipt_requires_fresh_log_and_static_canonical_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import finalize_known_cost_kernel_execution as finalizer

    kernel_root = tmp_path / "kernel"
    log_path = kernel_root / "logs" / f"kernel_{finalizer.GPU_JOB_ID}.log"
    log_path.parent.mkdir(parents=True)
    result_path = kernel_root / finalizer.KERNEL_RESULT_NAME
    result = {
        "kernel": [[1.0]],
        "kernel_orientation": "target-by-source",
        "decision": {
            "eligible_design": "four_arm_smoke_screen",
            "finite_step_ordering_passed": False,
        },
        "kernel_summary": {"median_off_diagonal": 0.75},
    }
    result_path.write_bytes(finalizer.canonical_json_bytes(result))
    run_summary = {
        "command": "run",
        "output": str(result_path),
        "output_sha256": finalizer.file_identity(result_path)["sha256"],
        "already_complete": False,
        "kernel": result["kernel"],
        "kernel_orientation": result["kernel_orientation"],
        "eligible_design": "four_arm_smoke_screen",
        "finite_step_ordering_passed": False,
        "median_off_diagonal": 0.75,
    }
    log_path.write_text("runtime prelude\n" + json.dumps(run_summary, indent=2, sort_keys=True) + "\n")
    assert finalizer.parse_final_run_summary(log_path, result)["already_complete"] is False
    forged = {**run_summary, "already_complete": True}
    log_path.write_text(json.dumps(forged, indent=2, sort_keys=True) + "\n")
    with pytest.raises(ValueError, match="freshly generated"):
        finalizer.parse_final_run_summary(log_path, result)

    scheduler = {
        "JobIDRaw": finalizer.GPU_JOB_ID,
        "JobName": finalizer.GPU_JOB_NAME,
        "State": "COMPLETED",
        "ExitCode": "0:0",
        "Submit": "2026-08-07T16:35:12",
        "Start": "2026-08-07T17:20:00",
        "End": "2026-08-07T17:20:01",
        "ElapsedRaw": "1",
        "QOS": finalizer.GPU_FINAL_QOS,
        "Account": finalizer.ACCOUNT,
        "Comment": "",
        "Timelimit": "00:45:00",
        "TimelimitRaw": "45",
    }
    assert (
        finalizer._completed_scheduler_record(
            scheduler,
            expected_name=finalizer.GPU_JOB_NAME,
            expected_qos=finalizer.GPU_FINAL_QOS,
            require_positive_elapsed=True,
        )["elapsed_seconds"]
        == 1
    )
    with pytest.raises(ValueError, match="did not complete"):
        finalizer._completed_scheduler_record(
            {**scheduler, "State": "FAILED"},
            expected_name=finalizer.GPU_JOB_NAME,
            expected_qos=finalizer.GPU_FINAL_QOS,
            require_positive_elapsed=True,
        )

    monkeypatch.setattr(finalizer, "PRODUCTION_KERNEL_ROOT", tmp_path)
    monkeypatch.setattr(finalizer, "_static_receipt_payload", lambda receipt, _: receipt)
    receipt = {
        "schema_version": finalizer.SCHEMA_VERSION,
        "artifact_type": finalizer.ARTIFACT_TYPE,
        "kernel_root": str(tmp_path),
        "pre_execution_witness": {},
        "scheduler_amendment": {},
        "scheduler_final_envelope": {},
        "finalizer_source_provenance": {},
        "source": {},
        "probe": {},
        "scheduler": {},
        "artifacts": {},
        "gpu_run_summary": {},
        "implementation": {},
        "checks": {},
    }
    receipt["payload_without_self_hash_sha256"] = finalizer.canonical_json_sha256(receipt)
    receipt_path = tmp_path / finalizer.RECEIPT_NAME
    receipt_path.write_bytes(finalizer.canonical_json_bytes(receipt))
    receipt_path.chmod(0o444)
    assert finalizer.validate_receipt(receipt_path)["receipt"] == receipt
    receipt_path.chmod(0o644)
    with pytest.raises(ValueError, match="writable"):
        finalizer.validate_receipt(receipt_path)
    receipt["forged"] = True
    receipt_path.write_bytes(finalizer.canonical_json_bytes(receipt))
    receipt_path.chmod(0o444)
    with pytest.raises(ValueError, match="exact top-level schema"):
        finalizer.validate_receipt(receipt_path)


def test_known_cost_fixed_pre_execution_witness_and_scheduler_amendment() -> None:
    import finalize_known_cost_kernel_execution as finalizer

    if not finalizer.PRODUCTION_KERNEL_ROOT.is_dir():
        pytest.skip("production known-cost kernel root is unavailable")
    witness = finalizer.validate_witness(finalizer.PRODUCTION_KERNEL_ROOT)
    amendment = finalizer.validate_scheduler_amendment(finalizer.PRODUCTION_KERNEL_ROOT, witness)
    envelope = finalizer.validate_scheduler_final_envelope(
        finalizer.PRODUCTION_KERNEL_ROOT,
        witness,
        amendment,
    )
    assert witness["identity"]["sha256"] == finalizer.PRODUCTION_WITNESS_SHA256
    assert amendment["identity"]["sha256"] == finalizer.PRODUCTION_AMENDMENT_SHA256
    assert envelope["identity"]["sha256"] == finalizer.PRODUCTION_ENVELOPE_SHA256
