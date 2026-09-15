"""Generate the evaluation report at /opt/ga_bench/evaluation_report.json."""

import json
import sys
import copy
import torch

sys.path.insert(0, "/opt/ga_bench")

from model import SmallCausalLM
from dataset import create_dataset, collate_sequences
from trainer import Trainer
from normalizers import STRATEGIES


def test_strategy(strategy_cls, scenario, ga_steps=4, seed=42):
    """Test a strategy against full-batch and return loss difference."""
    torch.manual_seed(seed)
    model = SmallCausalLM(vocab_size=512, dim=96, hidden_dim=192, n_layers=2)

    use_weights = "weighted" in scenario
    if "uniform" in scenario:
        seqs = create_dataset(ga_steps * 4, 512, 50, 50, seed=seed,
                              importance_weights=use_weights)
    else:
        seqs = create_dataset(ga_steps * 4, 512, 10, 100, seed=seed,
                              importance_weights=use_weights)

    batch = collate_sequences(seqs)

    model_fb = copy.deepcopy(model)
    model_ga = copy.deepcopy(model)

    trainer_fb = Trainer(model_fb, lr=0.01)
    loss_fb = trainer_fb.train_step_full_batch(batch)

    normalizer = strategy_cls()
    trainer_ga = Trainer(model_ga, lr=0.01, ga_steps=ga_steps,
                         normalizer=normalizer)
    loss_ga = trainer_ga.train_step_ga(batch)

    return abs(loss_fb - loss_ga)


def generate():
    scenarios = [
        "uniform_unweighted",
        "variable_unweighted",
        "uniform_weighted",
        "variable_weighted",
    ]

    evaluations = []

    for strat_name, strat_cls in STRATEGIES.items():
        if strat_name == "unified_correct":
            continue

        results = {}
        for scenario in scenarios:
            diff = test_strategy(strat_cls, scenario)
            results[scenario] = {
                "loss_difference": round(diff, 8),
                "is_correct": diff < 1e-5,
            }

        correct_scenarios = [s for s, r in results.items() if r["is_correct"]]
        incorrect_scenarios = [s for s, r in results.items()
                               if not r["is_correct"]]

        if strat_name == "naive_mean_scaling":
            math_reason = (
                "Computes (1/G)*sum(sum(CE_g)/n_g), a mean-of-means. "
                "When group sizes n_g differ (variable-length sequences), "
                "mean-of-means != mean-of-all. Ignores importance weights."
            )
        elif strat_name == "global_token_count":
            math_reason = (
                "Pre-computes N_total and uses sum(CE_g)/N_total per step. "
                "Correct for unweighted: sum_g[sum(CE_g)/N_total] = "
                "sum(CE)/N_total. Fails for weighted because it ignores "
                "importance weights, computing sum(CE)/N_total instead of "
                "sum(w*CE)/W_total."
            )
        elif strat_name == "per_step_weighted_mean":
            math_reason = (
                "Each step computes weighted mean sum(w*CE_g)/sum(w_g), "
                "then averages across steps with (1/G). This computes "
                "mean-of-weighted-means which != weighted-mean-of-all "
                "when weight sums sum(w_g) differ across minibatches. "
                "For unweighted, reduces to mean-of-means (same flaw as "
                "naive_mean_scaling)."
            )
        elif strat_name == "scaled_token_fraction":
            math_reason = (
                "Scales each step's mean by n_g/N_total. For unweighted: "
                "[sum(CE_g)/n_g]*[n_g/N_total] = sum(CE_g)/N_total, "
                "correct. For weighted: uses token fraction n_g/N_total "
                "instead of weight fraction sum(w_g)/W_total, so the "
                "re-weighting is wrong when weight distributions differ."
            )
        else:
            math_reason = "Custom strategy"

        evaluations.append({
            "strategy": strat_name,
            "correct_scenarios": correct_scenarios,
            "incorrect_scenarios": incorrect_scenarios,
            "scenario_results": results,
            "mathematical_reason": math_reason,
        })

    report = {
        "strategy_evaluations": evaluations,
        "unified_strategy_description": (
            "UnifiedNormalizer pre-computes W_total = sum of all effective "
            "weights (importance weights * non-padding mask) across ALL "
            "minibatches. For unweighted sequences, W_total = N_total "
            "(total non-padding tokens). Each minibatch computes "
            "sum(w_i * CE_i) / W_total (or sum(CE_i) / W_total for "
            "unweighted). Summing across GA steps gives "
            "sum(all w_i * CE_i) / W_total = full-batch weighted loss."
        ),
        "mathematical_justification": (
            "Full-batch loss: L = sum(w_i * CE_i) / W_total where "
            "W_total = sum(w_i). Split into G minibatches: "
            "L = sum_g[sum(w_i * CE_i for i in g)] / W_total. "
            "Each GA step contributes L_g = sum(w_i * CE_i for i in g) "
            "/ W_total. Then sum(L_g) = sum(all w_i * CE_i) / W_total "
            "= L. Gradients: d(L_g)/dtheta sums to d(L)/dtheta by "
            "linearity. Key insight: the normalizing denominator W_total "
            "must be GLOBAL (pre-computed across all minibatches), not "
            "local to each step. For unweighted case, w_i = 1 for "
            "non-padding, so W_total = N_total and this reduces to "
            "GlobalTokenCount (strategy 2)."
        ),
    }

    with open("/opt/ga_bench/evaluation_report.json", "w") as f:
        json.dump(report, f, indent=2)

    print("Generated /opt/ga_bench/evaluation_report.json")


if __name__ == "__main__":
    generate()
