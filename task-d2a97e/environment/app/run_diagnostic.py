"""Diagnostic script for comparing training configurations.

Run this after applying fixes to verify all configurations produce
consistent results.
"""

import torch
import copy
import math
from model import SmallCausalLM
from dataset import create_dataset, collate_sequences
from trainer import Trainer


def run_comparison(ga_steps, num_samples, min_len, max_len, seed=42, lr=0.01):
    """Run a single comparison between full-batch and GA training."""
    torch.manual_seed(seed)
    model = SmallCausalLM(vocab_size=512, dim=96, hidden_dim=192, n_layers=2)

    sequences = create_dataset(
        num_samples=num_samples,
        vocab_size=512,
        min_len=min_len,
        max_len=max_len,
        seed=seed,
    )
    batch = collate_sequences(sequences)

    model_fb = copy.deepcopy(model)
    model_ga = copy.deepcopy(model)

    trainer_fb = Trainer(model_fb, lr=lr, ga_steps=1)
    trainer_ga = Trainer(model_ga, lr=lr, ga_steps=ga_steps)

    loss_fb = trainer_fb.train_step_full_batch(batch)
    loss_ga = trainer_ga.train_step_ga(batch)

    loss_diff = abs(loss_fb - loss_ga)
    max_w = max(
        (p1 - p2).abs().max().item()
        for (_, p1), (_, p2) in zip(
            model_fb.named_parameters(), model_ga.named_parameters()
        )
    )

    return loss_fb, loss_ga, loss_diff, max_w


def main():
    print("=" * 70)
    print("Training Pipeline Diagnostic Report")
    print("=" * 70)

    # Check embedding scaling
    print("\n--- Embedding Scale Check ---")
    model = SmallCausalLM(vocab_size=512, dim=96, hidden_dim=192, n_layers=2)
    correct_scale = math.sqrt(96)
    print(f"Expected embedding scale: sqrt(96) = {correct_scale:.6f}")
    print(f"Model dim: {model.dim}")

    # GA vs Full-batch comparisons
    configs = [
        ("Variable lengths, GA=2", 2, 8, 10, 80, 42),
        ("Variable lengths, GA=4", 4, 16, 10, 80, 42),
        ("High variance, GA=4", 4, 16, 5, 200, 123),
        ("Equal lengths, GA=4", 4, 16, 50, 50, 99),
        ("Variable lengths, GA=8", 8, 24, 10, 100, 777),
    ]

    print("\n--- GA vs Full-Batch Comparison ---")
    print(
        f"{'Config':<30} {'Loss FB':>12} {'Loss GA':>12} "
        f"{'Diff':>12} {'Weight Diff':>12}"
    )
    print("-" * 80)

    all_pass = True
    for desc, ga, n, min_l, max_l, seed in configs:
        loss_fb, loss_ga, diff, w_diff = run_comparison(ga, n, min_l, max_l, seed)
        status = "OK" if diff < 1e-5 else "FAIL"
        if diff >= 1e-5:
            all_pass = False
        print(
            f"{desc:<30} {loss_fb:>12.8f} {loss_ga:>12.8f} "
            f"{diff:>12.2e} {w_diff:>12.2e}  [{status}]"
        )

    print("\n" + "=" * 70)
    if all_pass:
        print("All checks PASS")
    else:
        print("FAILURES detected - see above")
    print("=" * 70)


if __name__ == "__main__":
    main()
