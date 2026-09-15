"""Benchmark all normalization strategies against full-batch training.

Tests each strategy under four scenarios:
  - uniform_unweighted: all sequences same length, no weights
  - variable_unweighted: variable lengths, no weights
  - uniform_weighted: all sequences same length, with importance weights
  - variable_weighted: variable lengths, with importance weights

Results show which strategies produce correct loss values (matching
full-batch within tolerance) and which diverge.
"""

import torch
import copy
import sys

sys.path.insert(0, "/opt/ga_bench")

from model import SmallCausalLM
from dataset import create_dataset, collate_sequences
from trainer import Trainer
from normalizers import STRATEGIES


def benchmark_strategy(strategy_name, strategy_cls, scenario, ga_steps,
                       seed=42):
    """Test a strategy against full-batch for a given scenario."""
    torch.manual_seed(seed)

    model = SmallCausalLM(vocab_size=512, dim=96, hidden_dim=192, n_layers=2)

    use_weights = "weighted" in scenario
    if "uniform" in scenario:
        seqs = create_dataset(
            num_samples=ga_steps * 4, vocab_size=512,
            min_len=50, max_len=50, seed=seed,
            importance_weights=use_weights,
        )
    else:
        seqs = create_dataset(
            num_samples=ga_steps * 4, vocab_size=512,
            min_len=10, max_len=100, seed=seed,
            importance_weights=use_weights,
        )

    batch = collate_sequences(seqs)

    model_fb = copy.deepcopy(model)
    trainer_fb = Trainer(model_fb, lr=0.01, ga_steps=1)
    loss_fb = trainer_fb.train_step_full_batch(batch)

    model_ga = copy.deepcopy(model)
    normalizer = strategy_cls()
    trainer_ga = Trainer(model_ga, lr=0.01, ga_steps=ga_steps,
                         normalizer=normalizer)
    loss_ga = trainer_ga.train_step_ga(batch)

    diff = abs(loss_fb - loss_ga)
    match = diff < 1e-5

    return loss_fb, loss_ga, diff, match


def main():
    scenarios = [
        "uniform_unweighted",
        "variable_unweighted",
        "uniform_weighted",
        "variable_weighted",
    ]
    ga_steps_list = [2, 4]

    print("=" * 80)
    print("NORMALIZATION STRATEGY BENCHMARK")
    print("=" * 80)
    print()

    for scenario in scenarios:
        print(f"--- Scenario: {scenario} ---")
        for strategy_name, strategy_cls in STRATEGIES.items():
            for ga in ga_steps_list:
                fb, ga_loss, diff, match = benchmark_strategy(
                    strategy_name, strategy_cls, scenario, ga
                )
                status = "PASS" if match else "FAIL"
                print(
                    f"  [{status}] {strategy_name:30s} GA={ga}: "
                    f"fb={fb:.6f} ga={ga_loss:.6f} diff={diff:.2e}"
                )
        print()


if __name__ == "__main__":
    main()
