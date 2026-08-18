from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import tomli_w
from analyze_fixed_clock_sft_evals import (
    BANDS,
    BSG_ASSIGNMENTS,
    DOSE_LABELS,
    EXPECTED_OPERATIONS,
    EXPECTED_PROMPTS_PER_OPERATION,
    SELECTION_SEEDS,
    ValidatedResult,
    _difference_summary,
    _normalized_histogram_tv,
    _outcome_summary,
    _recipient_allocation_table,
    _recipient_feature_distances,
    _trend,
    bootstrap_band_values,
    build_logical_grid,
    dose_clock_analysis,
    exact_sign_flip_p,
    iid_channel_analysis,
    paired_contrast_cells,
    validate_runtime_config_semantics,
)


def _synthetic_manifests(tmp_path: Path) -> tuple[dict, dict, dict]:
    entries = [
        {
            "label": "c0_anchor",
            "alias_of": None,
            "selection_seed": SELECTION_SEEDS[-1],
            "clock": "anchor_only",
            "dose": "0/1",
            "dose_label": "p0000",
            "assignment": "clean",
            "hard_recipient_rows": 0,
            "raw_prefix_trajectories": 0,
            "rows": 512,
        }
    ]
    for seed in SELECTION_SEEDS:
        for dose in DOSE_LABELS:
            for assignment in BSG_ASSIGNMENTS:
                fixed_m_label = f"seed{seed}_fixed_m_{dose}_{assignment}"
                entries.append(
                    {
                        "label": fixed_m_label,
                        "alias_of": None,
                        "selection_seed": seed,
                        "clock": "fixed_m",
                        "dose": {"p0025": "1/400", "p0050": "1/200", "p0100": "1/100"}[dose],
                        "dose_label": dose,
                        "assignment": assignment,
                        "hard_recipient_rows": 512,
                        "raw_prefix_trajectories": 1_000,
                        "rows": 1_024,
                    }
                )
                if dose == "p0025":
                    entries.append(
                        {
                            **entries[-1],
                            "label": f"seed{seed}_fixed_raw_{dose}_{assignment}",
                            "alias_of": fixed_m_label,
                            "clock": "fixed_raw",
                        }
                    )
                else:
                    entries.append(
                        {
                            **entries[-1],
                            "label": f"seed{seed}_fixed_raw_{dose}_{assignment}",
                            "alias_of": None,
                            "clock": "fixed_raw",
                            "hard_recipient_rows": 1_024 if dose == "p0050" else 2_048,
                            "rows": 1_536 if dose == "p0050" else 2_560,
                        }
                    )
        for dose in DOSE_LABELS:
            iid_recipients = {"p0025": 2_500, "p0050": 5_000, "p0100": 10_000}[dose]
            entries.append(
                {
                    "label": f"seed{seed}_fixed_raw_{dose}_iid",
                    "alias_of": None,
                    "selection_seed": seed,
                    "clock": "fixed_raw",
                    "dose": {"p0025": "1/400", "p0050": "1/200", "p0100": "1/100"}[dose],
                    "dose_label": dose,
                    "assignment": "iid",
                    "hard_recipient_rows": iid_recipients,
                    "raw_prefix_trajectories": 1_000_001,
                    "iid_eligible_rows": 1_000_000,
                    "iid_realized_rate": iid_recipients / 1_000_000,
                    "candidate_overlap": iid_recipients // 4,
                    "rows": iid_recipients + 512,
                }
            )
    entries.sort(key=lambda entry: entry["label"])
    canonical = [entry for entry in entries if entry["alias_of"] is None]
    training_arms = []
    tasks = []
    for entry in canonical:
        final_step = None
        if entry["clock"] == "fixed_raw" and (entry["assignment"] == "iid" or entry["dose_label"] != "p0025"):
            final_step = 96 if entry["dose_label"] != "p0100" else 160
        readouts = [64] if final_step is None else [64, final_step]
        training_arms.append(
            {
                "label": entry["label"],
                "metadata": {
                    key: entry[key]
                    for key in (
                        "selection_seed",
                        "clock",
                        "dose",
                        "dose_label",
                        "assignment",
                        "hard_recipient_rows",
                        "raw_prefix_trajectories",
                    )
                },
                "rows": entry["rows"],
                "max_steps": readouts[-1],
                "two_pass_steps": final_step,
                "schedule": "common_64_steps" if final_step is None else "at_least_two_dataset_passes",
                "readout_steps": readouts,
            }
        )
        for step in readouts:
            task_index = len(tasks)
            tasks.append(
                {
                    "task_index": task_index,
                    "eval_id": f"{entry['label']}__step_{step}",
                    "arm_label": entry["label"],
                    "step": step,
                    "readout": "common" if step == 64 else "final",
                    "output_dir": str(tmp_path / entry["label"] / f"step_{step}"),
                }
            )
    return (
        {"study_id": "verifier_defect_fixed_clock_sft_v2", "arms": training_arms},
        {"arms": entries},
        {"study_id": "verifier_defect_fixed_clock_sft_eval_v1", "tasks": tasks},
    )


def _synthetic_results(grid: dict) -> dict[str, ValidatedResult]:
    results = {}
    for task in grid["task_by_eval_id"].values():
        assignment = grid["training_by_label"][task["arm_label"]]["metadata"]["assignment"]
        correct = {"behavior": 2, "shuffled": 1, "global": 0, "iid": 1, "clean": 0}[assignment]
        keys = {
            operation: tuple(
                (operation, index, f"op{operation}-{index}", 0) for index in range(EXPECTED_PROMPTS_PER_OPERATION)
            )
            for operation in EXPECTED_OPERATIONS
        }
        outcomes = {
            operation: tuple(index < correct for index in range(EXPECTED_PROMPTS_PER_OPERATION))
            for operation in EXPECTED_OPERATIONS
        }
        results[task["eval_id"]] = ValidatedResult(
            task=task,
            prompt_keys_by_op=keys,
            strict_by_op=outcomes,
            answer_by_op=outcomes,
            metrics={},
            artifacts={},
        )
    return results


def test_logical_grid_aliases_and_paired_contrasts(tmp_path: Path) -> None:
    training, arm_index, evaluation = _synthetic_manifests(tmp_path)
    grid = build_logical_grid(training, arm_index, evaluation)

    assert len(grid["task_by_eval_id"]) == 82
    assert len(grid["endpoints"]["common_step_64"]) == 64
    assert len(grid["endpoints"]["distinct_final"]) == 27
    assert len(grid["endpoints"]["fixed_raw_two_pass_mixed"]) == 27

    common = {
        (record["selection_seed"], record["clock"], record["dose_label"], record["assignment"]): record
        for record in grid["endpoints"]["common_step_64"]
        if record["assignment"] != "clean"
    }
    fixed_m = common[(SELECTION_SEEDS[0], "fixed_m", "p0025", "behavior")]
    fixed_raw = common[(SELECTION_SEEDS[0], "fixed_raw", "p0025", "behavior")]
    assert fixed_raw["is_alias"] is True
    assert fixed_raw["eval_id"] == fixed_m["eval_id"]
    mixed_alias = next(
        record
        for record in grid["endpoints"]["fixed_raw_two_pass_mixed"]
        if record["selection_seed"] == SELECTION_SEEDS[0]
        and record["dose_label"] == "p0025"
        and record["assignment"] == "behavior"
    )
    assert mixed_alias["source_two_pass_steps"] is None
    assert mixed_alias["logical_two_pass_steps"] == 64
    assert "byte-identical fixed-M" in mixed_alias["endpoint_provenance"]

    results = _synthetic_results(grid)
    cells = paired_contrast_cells("common_step_64", grid["endpoints"]["common_step_64"], results)
    assert len(cells) == 18
    first = cells[0]["contrasts"]
    band = "unseen_extrapolation_op41_45"
    assert first["b_minus_s"]["strict"]["bands"][band]["macro_difference"] == 1 / 200
    assert first["s_minus_g"]["strict"]["bands"][band]["macro_difference"] == 1 / 200
    assert first["b_minus_g"]["strict"]["bands"][band]["macro_difference"] == 2 / 200

    bootstrap = bootstrap_band_values(results, replicates=20, seed=7)
    iid = iid_channel_analysis(grid, results, bootstrap)
    assert len(iid["common_step_64_cells"]) == 9
    assert len(iid["common_step_64_by_dose"]) == 3
    assert len(iid["common_step_64_seed_dose_trends"]) == len(SELECTION_SEEDS) * len(BANDS)
    assert len(iid["distinct_final_iid_dose_trends"]) == len(SELECTION_SEEDS) * len(BANDS)
    first_iid_band = iid["common_step_64_cells"][0]["strict_iid_minus_clean"]["bands"][band]
    assert first_iid_band["macro_difference"] == 1 / 200
    assert iid["common_step_64_by_dose"][0]["bands"][band]["training_run_treatment_effect_test"] is None
    assert "share one C0" in iid["decision_guard"]


def test_band_trend_and_bootstrap_are_deterministic(tmp_path: Path) -> None:
    training, arm_index, evaluation = _synthetic_manifests(tmp_path)
    grid = build_logical_grid(training, arm_index, evaluation)
    results = _synthetic_results(grid)
    one_result = next(iter(results.values()))

    summary = _outcome_summary(one_result.strict_by_op)
    assert set(summary["bands"]) == set(BANDS)
    assert summary["bands"]["all_op11_45"]["macro_pass1"] == summary["bands"]["all_op11_45"]["micro_pass1"]
    differences = {operation: tuple([1, -1, *([0] * 198)]) for operation in EXPECTED_OPERATIONS}
    assert _difference_summary(differences)["bands"]["all_op11_45"]["macro_difference"] == 0.0
    assert _trend([0.1, 0.2, 0.5])["centered_log2_dose_slope_per_doubling"] == 0.2
    assert exact_sign_flip_p([1.0, 1.0, 1.0]) == 0.25

    first = bootstrap_band_values(results, replicates=20, seed=7)
    second = bootstrap_band_values(results, replicates=20, seed=7)
    eval_id = next(iter(results))
    for band in BANDS:
        assert np.array_equal(first[eval_id][band], second[eval_id][band])

    dose_clock = dose_clock_analysis(grid, results, first)
    assert len(dose_clock["common_step_64_across_seeds"]) == len(BANDS) * len(BSG_ASSIGNMENTS)
    primary = [
        record
        for record in dose_clock["common_step_64_across_seeds"]
        if record["confirmatory_status"] == "primary_H1_behavior"
    ]
    assert len(primary) == 2
    assert all(record["raw_minus_fixed_m_slope_interaction"]["mean"] == 0.0 for record in primary)
    assert all(
        "holm_p_across_two_primary_bands" in record["raw_minus_fixed_m_slope_interaction"]
        and "holm_p_across_exploratory_assignment_band_interactions"
        not in record["raw_minus_fixed_m_slope_interaction"]
        for record in primary
    )
    exploratory = [
        record for record in dose_clock["common_step_64_across_seeds"] if record["confirmatory_status"] == "exploratory"
    ]
    assert len(exploratory) == len(BANDS) * len(BSG_ASSIGNMENTS) - 2
    assert all(
        "holm_p_across_exploratory_assignment_band_interactions" in record["raw_minus_fixed_m_slope_interaction"]
        and "holm_p_across_two_primary_bands" not in record["raw_minus_fixed_m_slope_interaction"]
        for record in exploratory
    )


def test_runtime_inference_semantics_and_recipient_feature_distances(tmp_path: Path) -> None:
    base_inference_path = tmp_path / "base_inference.toml"
    runtime_inference_path = tmp_path / "runtime_inference.toml"
    base_inference = {
        "output_dir": str(tmp_path / "base-output"),
        "server": {"host": "0.0.0.0", "port": 20_000},
        "model": {"name": "/model", "dtype": "auto", "max_model_len": 2_048},
        "parallel": {"tp": 1, "dp": 1},
    }
    runtime_inference = copy.deepcopy(base_inference)
    runtime_inference["output_dir"] = str(tmp_path / "runtime-output")
    runtime_inference["server"]["port"] = 31_337
    base_inference_path.write_text(tomli_w.dumps(base_inference), encoding="utf-8")
    runtime_inference_path.write_text(tomli_w.dumps(runtime_inference), encoding="utf-8")
    base_eval = {
        "infer_config": str(base_inference_path),
        "evaluator": "/scorer.py",
        "eval": {"api_base_url": "http://127.0.0.1:20000/v1", "model": "/model", "operations": [11]},
    }
    runtime_eval = {
        **base_eval,
        "infer_config": str(runtime_inference_path),
        "eval": {**base_eval["eval"], "api_base_url": "http://127.0.0.1:31337/v1"},
    }
    validate_runtime_config_semantics(base_eval, runtime_eval)

    changed = copy.deepcopy(runtime_inference)
    changed["model"]["max_model_len"] = 4_096
    runtime_inference_path.write_text(tomli_w.dumps(changed), encoding="utf-8")
    with np.testing.assert_raises_regex(ValueError, "generation-semantic"):
        validate_runtime_config_semantics(base_eval, runtime_eval)

    distances = _recipient_feature_distances(
        {
            "value_mismatch_count": [1, 1],
            "dependency_mismatch_count": [0, 1],
            "missing_nodes": [1, 2],
            "extra_nodes": [0, 0],
            "model_input_tokens": [100, 200],
            "assistant_tokens": [50, 100],
            "answer_mismatch": [False, False],
            "finish_reason": ["stop", "stop"],
        },
        {
            "value_mismatch_count": [2, 2],
            "dependency_mismatch_count": [0, 1],
            "missing_nodes": [1, 3],
            "extra_nodes": [0, 1],
            "model_input_tokens": [100, 300],
            "assistant_tokens": [50, 150],
            "answer_mismatch": [False, True],
            "finish_reason": ["stop", "length"],
        },
    )
    assert distances["numeric"]["value_mismatch_count"]["mean_difference_right_minus_left"] == 1.0
    assert distances["categorical"]["answer_mismatch"]["total_variation_distance"] == 0.5


def test_recipient_allocation_summary_validates_prompt_counts(tmp_path: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    path = tmp_path / "allocation.parquet"
    rows = [
        {
            "op": 21,
            "prompt_index": 1,
            "prompt_id": "p1",
            "source_kind": "defect_recipient",
            "assignment": "shuffled",
            "candidate": True,
            "group_extra_positive_count": 2,
        },
        {
            "op": 21,
            "prompt_index": 1,
            "prompt_id": "p1",
            "source_kind": "defect_recipient",
            "assignment": "shuffled",
            "candidate": False,
            "group_extra_positive_count": 2,
        },
        {
            "op": 22,
            "prompt_index": 2,
            "prompt_id": "p2",
            "source_kind": "defect_recipient",
            "assignment": "shuffled",
            "candidate": False,
            "group_extra_positive_count": 1,
        },
        {
            "op": 10,
            "prompt_index": 3,
            "prompt_id": "anchor",
            "source_kind": "clean_anchor",
            "assignment": "clean",
            "candidate": False,
            "group_extra_positive_count": 0,
        },
    ]
    pq.write_table(pa.Table.from_pylist(rows), path)

    summary, groups = _recipient_allocation_table(path, expected_rows=3, expected_assignment="shuffled")

    assert summary["candidate_overlap_rows"] == 1
    assert summary["counts_by_operation"]["21"] == 2
    assert summary["counts_by_operation"]["22"] == 1
    assert summary["distinct_prompt_groups"] == 2
    assert summary["recipient_count_per_prompt_histogram"] == {"1": 1, "2": 1}
    assert groups == ((21, 1, "p1", 2), (22, 2, "p2", 1))
    assert _normalized_histogram_tv({"1": 2}, {"1": 1, "2": 1}) == 0.5
