from __future__ import annotations

import numpy as np
import pytest
from analyze_verifier_clock_pairs import (
    BANDS,
    CheckpointScores,
    audit_eval_policy_versions,
    frontier_curve_sensitivity,
    paired_band_contrast,
    validate_pairing,
)


def checkpoint(label: str, scores: list[int], *, prompt_suffix: str = "") -> CheckpointScores:
    keys = ((15, 0), (15, 1), (16, 0), (16, 1))
    return CheckpointScores(
        label=label,
        step=100,
        keys=keys,
        prompt_hashes=tuple(f"prompt-{operation}-{index}{prompt_suffix}" for operation, index in keys),
        scores=np.asarray(scores, dtype=np.int8),
        files=(),
    )


def test_paired_contrast_and_prompt_identity() -> None:
    assert "hard_train_op21_40" in BANDS
    assert "strict_dead_train_op21_40" not in BANDS
    control = checkpoint("p00", [1, 0, 0, 1])
    treatment = checkpoint("p01", [1, 1, 0, 0])
    validate_pairing({"p00": control, "p01": treatment})

    contrast = paired_band_contrast(
        control,
        treatment,
        (15, 16),
        bootstrap_replicates=1_000,
        bootstrap_seed=7,
    )

    assert contrast["prompts"] == 4
    assert contrast["paired_difference_treatment_minus_control_pp"] == 0.0
    assert contrast["discordant"] == {
        "treatment_only_correct": 1,
        "control_only_correct": 1,
        "total": 2,
    }
    assert contrast["exact_mcnemar_two_sided_p"] == 1.0
    assert contrast["paired_stratified_bootstrap_95_interval_pp"] == [-50.0, 50.0]

    with pytest.raises(ValueError, match="Prompt texts differ"):
        validate_pairing({"p00": control, "p01": checkpoint("p01", [1, 1, 0, 0], prompt_suffix="-changed")})


def test_policy_version_audit_reads_all_requested_steps_once(tmp_path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    lines = []
    for step in (25, 50):
        for operation in (11, 12):
            lines.extend(
                (
                    f"Eval heldout-op{operation}-strict step {step} had mixed policy versions: "
                    f"[{step - 1}, {step}, {step + 1}]\n",
                    f"Evaluated heldout-op{operation}-strict (Step {step}) | Policy v{step - 1} | Reward 0.0\n",
                )
            )
    (log_dir / "orchestrator.log").write_text("".join(lines), encoding="utf-8")

    audit = audit_eval_policy_versions(tmp_path, {25, 50}, operations=(11, 12))

    assert audit["requested_steps"] == [25, 50]
    assert audit["selected_policy_records"]["count"] == 8
    assert audit["checkpoints"]["25"]["completion_policy_label_histogram"] == {"24": 2}
    assert audit["checkpoints"]["50"]["mixed_version_set_histogram"] == {"[49,50,51]": 2}
    assert audit["checkpoints"]["25"]["all_operations_mixed"] is True
    assert audit["checkpoints"]["50"]["all_operations_have_expected_adjacent_versions"] is True


@pytest.mark.parametrize(
    ("case", "content", "operations", "message"),
    (
        (
            "wrong-minimum",
            "Eval heldout-op11-strict step 25 had mixed policy versions: [24, 25, 26]\n"
            "Evaluated heldout-op11-strict (Step 25) | Policy v25 | Reward 0.0\n",
            (11,),
            "not the minimum",
        ),
        (
            "missing-completion",
            "Evaluated heldout-op11-strict (Step 25) | Policy v24 | Reward 0.0\n",
            (11, 12),
            "completions differ",
        ),
        (
            "duplicate-completion",
            "Evaluated heldout-op11-strict (Step 25) | Policy v24 | Reward 0.0\n"
            "Evaluated heldout-op11-strict (Step 25) | Policy v24 | Reward 0.0\n",
            (11,),
            "Duplicate",
        ),
    ),
)
def test_policy_version_audit_rejects_invalid_provenance(
    tmp_path, case: str, content: str, operations: tuple[int, ...], message: str
) -> None:
    run_root = tmp_path / case
    log_dir = run_root / "logs"
    log_dir.mkdir(parents=True)
    (log_dir / "orchestrator.log").write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        audit_eval_policy_versions(run_root, {25}, operations=operations)


def test_frontier_curve_sensitivity_separates_optimizer_and_exposure_clocks() -> None:
    summary = {
        "common_log_proxy_exposure_interval": [0, 1_000],
        "runs": {
            "p00": {
                "curve": [
                    {"step": 0, "frontier_op15_17_percent": 0.0},
                    {"step": 10, "frontier_op15_17_percent": 10.0},
                    {"step": 20, "frontier_op15_17_percent": 20.0},
                ],
                "frontier_op15_17_auc_percent": 8.0,
            },
            "p01": {
                "curve": [
                    {"step": 0, "frontier_op15_17_percent": 0.0},
                    {"step": 10, "frontier_op15_17_percent": 20.0},
                    {"step": 20, "frontier_op15_17_percent": 20.0},
                ],
                "frontier_op15_17_auc_percent": 11.0,
            },
            "p05": {
                "curve": [
                    {"step": 0, "frontier_op15_17_percent": 0.0},
                    {"step": 10, "frontier_op15_17_percent": 0.0},
                    {"step": 20, "frontier_op15_17_percent": 0.0},
                ],
                "frontier_op15_17_auc_percent": 7.0,
            },
        },
    }

    sensitivity = frontier_curve_sensitivity(summary, 20, last_common_evals=2)

    optimizer = sensitivity["optimizer_step_clock"]
    assert optimizer["normalized_trapezoid_auc_percent"] == {"p00": 10.0, "p01": 15.0, "p05": 0.0}
    assert optimizer["last_common_evaluation_steps"] == [10, 20]
    assert optimizer["mean_over_last_common_evaluations_percent"] == {"p00": 15.0, "p01": 20.0, "p05": 0.0}
    assert sensitivity["log_proxy_exposure_clock"]["contrasts_to_p00_pp"] == {
        "p01_minus_p00": 3.0,
        "p05_minus_p00": -1.0,
    }
